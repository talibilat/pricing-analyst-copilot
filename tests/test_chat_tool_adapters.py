"""Composition-level tests for the ChatToolFacade integration surface.

These prove correct wiring, envelope shape/status semantics, and JSON-
serializability of every method's return value. SQL injection edge cases are
covered exhaustively by Task 1's persistent-database suite, not re-tested here.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pricing_copilot.chat.contracts import ChatActivity, ChatContext, ChatResponse
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
from pricing_copilot.data.persistent import build_analytics_database
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.governance_agent import FakeGovernanceAgentRunner
from pricing_copilot.orchestration.pipeline import OrchestrationBundle
from pricing_copilot.orchestration.recommendation_agent import FakeRecommendationAgentRunner
from pricing_copilot.orchestration.specialists import FakeSpecialistAgent
from pricing_copilot.replay.store import save_replay_artifact

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
    """Settings with fresh, empty artifact directories and a real analytics DB."""
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
    def factory(
        *, analytics: Any, documents: Any, region: Region
    ) -> dict[EvidenceDomain, FakeSpecialistAgent]:
        return {
            domain: FakeSpecialistAgent(SpecialistFindings(summary=f"{domain.value} ok"))
            for domain in EvidenceDomain
        }

    return OrchestrationBundle(
        specialist_agents_factory=factory,
        recommendation_agent=FakeRecommendationAgentRunner(),
        governance_agent=FakeGovernanceAgentRunner(),
    )


_ENVELOPE_KEYS = {"status", "source", "data", "citations", "error"}


def _assert_envelope(result: dict[str, object]) -> None:
    assert set(result) == _ENVELOPE_KEYS
    assert result["status"] in {"ok", "not_found", "blocked"}
    # The whole envelope must survive json.dumps - a raw date/datetime would raise.
    json.dumps(result)


# --------------------------------------------------------------------------- #
# describe_analytics_schema                                                    #
# --------------------------------------------------------------------------- #


def test_describe_analytics_schema_returns_ok_catalogue(facade: ChatToolFacade) -> None:
    result = facade.describe_analytics_schema()
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "analytics_database"
    assert result["citations"] == []
    data = result["data"]
    assert isinstance(data, dict)
    assert data["tables"]
    assert data["database_version"]


# --------------------------------------------------------------------------- #
# execute_read_only_sql                                                        #
# --------------------------------------------------------------------------- #


def test_execute_read_only_sql_returns_ok_with_serialized_rows(facade: ChatToolFacade) -> None:
    result = facade.execute_read_only_sql(
        "SELECT period, incurred_loss_gbp FROM claims WHERE region = 'north_west'",
        ScenarioName.CONTROLLED_INCREASE,
    )
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "analytics_database"
    assert result["citations"] == []
    data = result["data"]
    assert isinstance(data, dict)
    assert data["columns"] == ["period", "incurred_loss_gbp"]
    assert data["rows"]
    # The period column is a date and must have been serialized to an ISO string.
    assert isinstance(data["rows"][0][0], str)
    assert data["database_version"]


def test_execute_read_only_sql_blocks_unsafe_statement(facade: ChatToolFacade) -> None:
    result = facade.execute_read_only_sql(
        "SELECT period FROM claims; DROP TABLE claims",
        ScenarioName.CONTROLLED_INCREASE,
    )
    _assert_envelope(result)
    assert result["status"] == "blocked"
    assert result["data"] == {}
    assert isinstance(result["error"], str)
    assert result["error"]


# --------------------------------------------------------------------------- #
# search_documents                                                            #
# --------------------------------------------------------------------------- #


def test_search_documents_returns_ok_documents(facade: ChatToolFacade) -> None:
    result = facade.search_documents(
        "north west motor market pricing pressure",
        ScenarioName.CONTROLLED_INCREASE,
        Region.NORTH_WEST,
        top_k=12,
    )
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "document_corpus"
    data = result["data"]
    assert isinstance(data, dict)
    assert data["documents"]
    first = data["documents"][0]
    assert set(first) >= {
        "document_id",
        "title",
        "snippet",
        "source_type",
        "sentiment",
        "score",
        "chunk_id",
        "source",
        "publication_date",
        "retrieval_score",
    }
    # Citations are exactly the returned (post-quarantine) document ids.
    assert result["citations"] == [doc["document_id"] for doc in data["documents"]]


def test_search_documents_excludes_quarantined_document(facade: ChatToolFacade) -> None:
    result = facade.search_documents(
        "market pulse november north west motor",
        ScenarioName.CONTROLLED_INCREASE,
        Region.NORTH_WEST,
        top_k=12,
    )
    _assert_envelope(result)
    assert result["status"] == "ok"
    returned_ids = result["citations"]
    assert isinstance(returned_ids, list)
    # The adversarial document is retrievable but must be quarantined out.
    assert "doc-market-2025-11-adversarial" not in returned_ids


# --------------------------------------------------------------------------- #
# load_replay                                                                 #
# --------------------------------------------------------------------------- #


def test_load_replay_not_found_when_empty(facade: ChatToolFacade) -> None:
    result = facade.load_replay(ScenarioName.CONTROLLED_INCREASE)
    _assert_envelope(result)
    assert result["status"] == "not_found"
    assert result["source"] == "replay_artifact"
    assert result["data"] == {}
    assert isinstance(result["error"], str) and result["error"]


def test_load_replay_returns_ok_for_recorded_artifact(
    facade: ChatToolFacade, settings: Settings
) -> None:
    # Record a fresh, compatible artifact by running the governed workflow with fakes.
    with patch(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        return_value=_fake_bundle(),
    ):
        run = facade.run_recommendation(_question(ScenarioName.CONTROLLED_INCREASE))
    from pricing_copilot.contracts import WorkflowResult

    workflow_result = WorkflowResult.model_validate(run["data"])
    response = ChatResponse(
        intent="pricing_analysis",
        message="recorded",
        context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
        workflow_result=workflow_result,
        cited_evidence_ids=workflow_result.recommendation.cited_evidence_ids,
    )
    save_replay_artifact(response, settings)

    result = facade.load_replay(ScenarioName.CONTROLLED_INCREASE)
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "replay_artifact"
    data = result["data"]
    assert isinstance(data, dict)
    assert data["recorded_at"]
    assert data["configuration_versions"]
    assert data["workflow_result"]
    assert result["citations"] == list(workflow_result.recommendation.cited_evidence_ids)


# --------------------------------------------------------------------------- #
# load_evaluation and load_drift                                              #
# --------------------------------------------------------------------------- #


def test_load_evaluation_not_found_when_empty(facade: ChatToolFacade) -> None:
    result = facade.load_evaluation()
    _assert_envelope(result)
    assert result["status"] == "not_found"
    assert result["source"] == "evaluation_report"
    assert result["data"] == {}
    assert isinstance(result["error"], str) and result["error"]


def test_load_drift_not_found_when_empty(facade: ChatToolFacade) -> None:
    result = facade.load_drift()
    _assert_envelope(result)
    assert result["status"] == "not_found"
    assert result["source"] == "drift_report"
    assert result["data"] == {}
    assert isinstance(result["error"], str) and result["error"]


def test_load_evaluation_returns_ok_for_recorded_report(
    facade: ChatToolFacade, settings: Settings
) -> None:
    from pricing_copilot.evaluation.store import load_benchmark_report, save_benchmark_report

    # Reuse the committed benchmark report as realistic recorded content.
    committed = load_benchmark_report(Settings())
    assert committed is not None
    save_benchmark_report(committed, settings)

    result = facade.load_evaluation()
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "evaluation_report"
    assert isinstance(result["data"], dict) and result["data"]
    assert result["citations"] == []


def test_load_drift_returns_ok_for_recorded_report(
    facade: ChatToolFacade, settings: Settings
) -> None:
    from pricing_copilot.drift.store import load_drift_report, save_drift_report

    committed = load_drift_report(Settings())
    assert committed is not None
    save_drift_report(committed, settings)

    result = facade.load_drift()
    _assert_envelope(result)
    assert result["status"] == "ok"
    assert result["source"] == "drift_report"
    assert isinstance(result["data"], dict) and result["data"]
    assert result["citations"] == []


# --------------------------------------------------------------------------- #
# run_recommendation                                                          #
# --------------------------------------------------------------------------- #


def test_run_recommendation_ok_with_citations_and_activity(facade: ChatToolFacade) -> None:
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
    assert result["source"] == "live"
    assert result["citations"]
    data = result["data"]
    assert isinstance(data, dict)
    assert data["governance_outcome"]["approved"] is True
    assert data["recommendation"]["cited_evidence_ids"]
    # Activity forwarding actually produced at least one presentation-worthy event.
    assert activities
    assert all(isinstance(activity, ChatActivity) for activity in activities)


def test_run_recommendation_blocked_on_missing_credentials(facade: ChatToolFacade) -> None:
    with patch(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        side_effect=RuntimeError("Azure OpenAI credentials are not configured."),
    ):
        result = facade.run_recommendation(_question(ScenarioName.CONTROLLED_INCREASE))
    _assert_envelope(result)
    assert result["status"] == "blocked"
    assert result["data"] == {}
    assert isinstance(result["error"], str)
    assert result["error"].startswith("workflow:")
