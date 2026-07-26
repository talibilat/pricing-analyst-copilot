"""Focused end-to-end and security coverage for ``ChatToolFacade``.

These tests exercise the facade exactly as the conversation agent will: through
its public methods only, asserting on the ``{status, source, data, citations,
error}`` envelope. They deliberately require neither Streamlit nor live model
credentials - the whole point of this suite is that it runs without either.

Each test maps to one of the nine numbered scenarios in
``.superpowers/sdd/task-4-brief.md``; the mapping is called out in the section
banners below. The assertions are written so that removing the underlying
protection (scenario scoping, the row cap, SQL validation, document quarantine,
recoverable-error envelopes, or the fail-loud contract) would make the test fail.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pricing_copilot.chat.contracts import ChatActivity
from pricing_copilot.chat.tool_adapters import ChatToolFacade
from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.data.persistent import (
    FREEFORM_ROW_LIMIT,
    PersistentAnalyticsDatabase,
    build_analytics_database,
)
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.governance_agent import FakeGovernanceAgentRunner
from pricing_copilot.orchestration.pipeline import OrchestrationBundle
from pricing_copilot.orchestration.recommendation_agent import FakeRecommendationAgentRunner
from pricing_copilot.orchestration.specialists import FakeSpecialistAgent, SpecialistAgent

# The synthetic, fictional competitor names this project's fixture data uses.
# Confirmed against ``data.generation.COMPETITOR_BASE_INDEX``.
FICTIONAL_COMPETITORS = {"Meridian Insure", "Northgate Cover", "Bracken Mutual"}
# The adversarial prompt-injection fixture document that must always be quarantined.
ADVERSARIAL_DOCUMENT_ID = "doc-market-2025-11-adversarial"

_ENVELOPE_KEYS = {"status", "source", "data", "citations", "error"}


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def analytics_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the versioned analytics DuckDB once for the whole module."""
    path = tmp_path_factory.mktemp("analytics") / "synthetic.duckdb"
    return build_analytics_database(path)


@pytest.fixture
def settings(analytics_db_path: Path, tmp_path: Path) -> Settings:
    """Settings with a real analytics DB and fresh, empty artifact directories.

    Because ``replay_directory``/``evaluation_directory``/``drift_directory`` all
    point into an empty per-test ``tmp_path``, nothing has ever been recorded
    there - which is exactly what scenario 7 relies on.
    """
    return Settings(
        analytics_database_path=analytics_db_path,
        replay_directory=tmp_path / "replay",
        evaluation_directory=tmp_path / "evaluation",
        drift_directory=tmp_path / "drift",
        local_tracing_enabled=False,
    )


@pytest.fixture
def facade(settings: Settings) -> ChatToolFacade:
    return ChatToolFacade(settings)


def _question(scenario: ScenarioName) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)),
        scenario=scenario,
    )


def _fake_bundle() -> OrchestrationBundle:
    """A deterministic orchestration built from the project's existing test doubles.

    Identical pattern to ``tests/test_orchestration_pipeline.py``'s ``_bundle``:
    it lets ``run_recommendation`` run the full governed workflow without any
    Azure OpenAI call.
    """

    def factory(
        *, analytics: Any, documents: Any, region: Region
    ) -> dict[EvidenceDomain, SpecialistAgent]:
        return {
            domain: FakeSpecialistAgent(SpecialistFindings(summary=f"{domain.value} ok"))
            for domain in EvidenceDomain
        }

    return OrchestrationBundle(
        specialist_agents_factory=factory,
        recommendation_agent=FakeRecommendationAgentRunner(),
        governance_agent=FakeGovernanceAgentRunner(),
    )


def _assert_envelope(result: dict[str, object]) -> None:
    """Every facade answer is a JSON-serializable envelope with the exact keys."""
    assert set(result) == _ENVELOPE_KEYS
    assert result["status"] in {"ok", "not_found", "blocked"}
    # A raw date/datetime cell would raise here; serializability is part of the contract.
    json.dumps(result)


# --------------------------------------------------------------------------- #
# Scenario 1: Schema discovery returns all four business tables and units.     #
# --------------------------------------------------------------------------- #


def test_schema_discovery_names_four_business_tables_with_units(facade: ChatToolFacade) -> None:
    result = facade.describe_analytics_schema()
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "analytics_database"

    data = result["data"]
    assert isinstance(data, dict)
    tables = data["tables"]
    assert isinstance(tables, list)
    table_names = {table["name"] for table in tables}
    assert table_names == {"claims", "conversion", "competitors", "pricing_history"}

    # Every column of every business table carries unit metadata, and at least one
    # concrete unit ("GBP") is present so this is not vacuously true.
    all_units: set[str] = set()
    for table in tables:
        for column in table["columns"]:
            assert "unit" in column
            assert isinstance(column["unit"], str) and column["unit"]
            all_units.add(column["unit"])
    assert "GBP" in all_units


# --------------------------------------------------------------------------- #
# Scenario 2: A last-month premium query returns only the selected scenario.   #
# --------------------------------------------------------------------------- #


def test_premium_query_is_scenario_scoped_at_the_facade_surface(facade: ChatToolFacade) -> None:
    # A claims premium/economics query for the period series. ``earned_premium_gbp``
    # is scenario-independent by design, so the projection also carries
    # ``incurred_loss_gbp`` (the canonical scenario-differentiating figure) - that
    # is what makes "only the selected scenario's rows" an observable claim.
    sql = "SELECT period, earned_premium_gbp, incurred_loss_gbp FROM claims ORDER BY period"

    controlled = facade.execute_read_only_sql(sql, ScenarioName.CONTROLLED_INCREASE)
    retention = facade.execute_read_only_sql(sql, ScenarioName.RETENTION_CONCERN)

    _assert_envelope(controlled)
    _assert_envelope(retention)
    assert controlled["status"] == "ok"
    assert retention["status"] == "ok"

    controlled_data = controlled["data"]
    retention_data = retention["data"]
    assert isinstance(controlled_data, dict)
    assert isinstance(retention_data, dict)
    assert controlled_data["columns"] == ["period", "earned_premium_gbp", "incurred_loss_gbp"]
    assert controlled_data["rows"]
    assert retention_data["rows"]
    # The very same SQL string, scoped to two different scenarios, must return
    # different premium slices: scenario scoping is wired through the facade, not
    # bypassable from the query text.
    assert controlled_data["rows"] != retention_data["rows"]


# --------------------------------------------------------------------------- #
# Scenario 3: A competitor query returns fictional competitor names.           #
# --------------------------------------------------------------------------- #


def test_competitor_query_returns_only_fictional_competitor_names(facade: ChatToolFacade) -> None:
    result = facade.execute_read_only_sql(
        "SELECT DISTINCT competitor_name FROM competitors",
        ScenarioName.CONTROLLED_INCREASE,
    )
    _assert_envelope(result)
    assert result["status"] == "ok"

    data = result["data"]
    assert isinstance(data, dict)
    assert data["columns"] == ["competitor_name"]
    returned_names = {row[0] for row in data["rows"]}
    assert returned_names
    # Every returned name is one of the known synthetic competitors - no real
    # insurer names leak through the fictional-data boundary.
    assert returned_names <= FICTIONAL_COMPETITORS


# --------------------------------------------------------------------------- #
# Scenario 4: Safe user SELECT executes and is capped at 200 rows.             #
# --------------------------------------------------------------------------- #


def test_safe_select_is_capped_at_two_hundred_rows(facade: ChatToolFacade) -> None:
    # A self cross-join of a 24-row scenario slice matches 576 rows; the engine-
    # level cap must trim the envelope's rows to exactly 200.
    result = facade.execute_read_only_sql(
        "SELECT c1.period FROM claims AS c1 CROSS JOIN claims AS c2",
        ScenarioName.CONTROLLED_INCREASE,
    )
    _assert_envelope(result)
    assert result["status"] == "ok"
    data = result["data"]
    assert isinstance(data, dict)
    rows = data["rows"]
    assert isinstance(rows, list)
    assert len(rows) == FREEFORM_ROW_LIMIT == 200


# --------------------------------------------------------------------------- #
# Scenario 5: Writes, external files, table functions, prohibited fields, and  #
# scenario bypasses are blocked before execution.                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("category", "sql"),
    [
        ("mutation", "DELETE FROM claims"),
        ("external_file_or_table_function", "SELECT * FROM read_csv('/etc/passwd')"),
        ("prohibited_field", "SELECT customer_id FROM claims"),
        ("scenario_bypass", "SELECT period FROM claims WHERE scenario = 'retention_concern'"),
    ],
)
def test_unsafe_sql_is_blocked_before_execution(
    facade: ChatToolFacade, category: str, sql: str
) -> None:
    result = facade.execute_read_only_sql(sql, ScenarioName.CONTROLLED_INCREASE)
    _assert_envelope(result)
    assert result["status"] == "blocked", category
    assert result["data"] == {}
    assert isinstance(result["error"], str)
    assert result["error"]


def test_blocked_mutation_never_takes_effect(facade: ChatToolFacade) -> None:
    count_sql = "SELECT COUNT(period) AS n FROM claims"

    def _row_count() -> int:
        envelope = facade.execute_read_only_sql(count_sql, ScenarioName.CONTROLLED_INCREASE)
        assert envelope["status"] == "ok"
        data = envelope["data"]
        assert isinstance(data, dict)
        return int(data["rows"][0][0])

    before = _row_count()
    assert before > 0

    blocked = facade.execute_read_only_sql("DELETE FROM claims", ScenarioName.CONTROLLED_INCREASE)
    assert blocked["status"] == "blocked"

    # The mutation was rejected before execution, so the scenario slice is intact.
    assert _row_count() == before


# --------------------------------------------------------------------------- #
# Scenario 6: Document search returns evidence IDs and excludes quarantined    #
# content.                                                                     #
# --------------------------------------------------------------------------- #


def test_document_search_returns_citations_and_excludes_quarantined_document(
    facade: ChatToolFacade,
) -> None:
    query = "north west competitor repricing market briefing"

    # Precondition: the adversarial document is genuinely retrievable for this
    # scenario/region and query, so excluding it is a real quarantine action and
    # not an artifact of it simply never matching.
    raw = retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        region=Region.NORTH_WEST,
        query=query,
        top_k=12,
    )
    raw_ids = {item.document.document_id for item in raw}
    assert ADVERSARIAL_DOCUMENT_ID in raw_ids

    result = facade.search_documents(
        query, ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST, top_k=12
    )
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "document_corpus"

    data = result["data"]
    assert isinstance(data, dict)
    documents = data["documents"]
    assert isinstance(documents, list)
    citations = result["citations"]
    assert isinstance(citations, list)

    # Real, safe documents surfaced -> non-empty evidence IDs that mirror the docs.
    assert citations
    assert citations == [doc["document_id"] for doc in documents]
    # The adversarial fixture is filtered out of both the payload and the citations.
    returned_ids = {doc["document_id"] for doc in documents}
    assert ADVERSARIAL_DOCUMENT_ID not in returned_ids
    assert ADVERSARIAL_DOCUMENT_ID not in citations


# --------------------------------------------------------------------------- #
# Scenario 7: Missing replay, evaluation, and drift artifacts return           #
# recoverable ``not_found`` payloads.                                          #
# --------------------------------------------------------------------------- #


def test_missing_artifacts_return_recoverable_not_found(facade: ChatToolFacade) -> None:
    envelopes = {
        "replay": facade.load_replay(ScenarioName.CONTROLLED_INCREASE),
        "evaluation": facade.load_evaluation(),
        "drift": facade.load_drift(),
    }
    for name, envelope in envelopes.items():
        _assert_envelope(envelope)
        assert envelope["status"] == "not_found", name
        assert envelope["data"] == {}, name
        assert isinstance(envelope["error"], str) and envelope["error"], name
        # A recoverable payload is still fully serializable for the caller to show.
        json.dumps(envelope)


# --------------------------------------------------------------------------- #
# Scenario 8: Stubbed recommendation dispatch preserves the governed workflow  #
# result and activity events.                                                  #
# --------------------------------------------------------------------------- #


def test_recommendation_preserves_governed_result_and_forwards_activities(
    facade: ChatToolFacade,
) -> None:
    activities: list[ChatActivity] = []

    with patch(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        return_value=_fake_bundle(),
    ):
        result = facade.run_recommendation(
            _question(ScenarioName.CONTROLLED_INCREASE),
            on_activity=activities.append,
        )

    _assert_envelope(result)
    assert result["status"] == "ok"

    data = result["data"]
    assert isinstance(data, dict)
    assert data["recommendation"]["cited_evidence_ids"]
    assert data["governance_outcome"]["approved"] is True

    citations = result["citations"]
    assert isinstance(citations, list) and citations

    # Activity translation and forwarding actually ran end to end: the listener
    # received real ChatActivity instances, not raw trace events.
    assert activities
    assert all(isinstance(activity, ChatActivity) for activity in activities)


# --------------------------------------------------------------------------- #
# Scenario 9: Unexpected tool failures remain visible rather than becoming     #
# fabricated answers.                                                          #
# --------------------------------------------------------------------------- #


def test_unexpected_document_failure_propagates_instead_of_fabricating(
    facade: ChatToolFacade,
) -> None:
    # ``search_documents`` looks ``retrieve_documents`` up in the facade module's
    # namespace, so that binding is what must be patched to simulate a genuine
    # programming/dependency failure.
    with patch(
        "pricing_copilot.chat.tool_adapters.retrieve_documents",
        side_effect=RuntimeError("unexpected failure"),
    ):
        with pytest.raises(RuntimeError, match="unexpected failure"):
            facade.search_documents(
                "any query", ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST
            )


def test_unexpected_analytics_failure_propagates_instead_of_fabricating(
    facade: ChatToolFacade,
) -> None:
    # ``execute_read_only_sql`` catches only ``ValueError`` (the validator's
    # rejection). A different exception type from deeper in the analytics path is
    # a programming error and must surface, never be swallowed into an envelope.
    with patch.object(
        PersistentAnalyticsDatabase,
        "execute_freeform_sql",
        side_effect=RuntimeError("unexpected failure"),
    ):
        with pytest.raises(RuntimeError, match="unexpected failure"):
            facade.execute_read_only_sql(
                "SELECT period FROM claims", ScenarioName.CONTROLLED_INCREASE
            )
