from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecisionType,
    DecisionRequest,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    ResultSource,
    ScenarioName,
    Segment,
)
from pricing_copilot.decisions.service import record_analyst_decision
from pricing_copilot.decisions.store import DecisionStore


def _request(
    decision: AnalystDecisionType,
    rationale: str,
    conditions: list[str] | None = None,
    source: ResultSource = ResultSource.LIVE,
) -> DecisionRequest:
    return DecisionRequest(
        question=PortfolioQuestion(
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            analysis_period=AnalysisPeriod(
                start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)
            ),
            scenario=None,
        ),
        recommendation=Recommendation(
            action=RecommendationAction.INCREASE,
            rationale="test",
            cited_evidence_ids=["claims-north_west-2025-12-01"],
        ),
        governance_outcome=GovernanceOutcome(approved=True),
        decision=decision,
        rationale=rationale,
        conditions=conditions or [],
        source=source,
    )


def test_record_decision_persists_and_returns_full_record(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    settings = Settings()

    recorded = record_analyst_decision(
        _request(AnalystDecisionType.APPROVE, "Evidence supports the recommendation."),
        settings,
        store,
    )

    assert recorded.record_id is not None
    assert recorded.evidence_ids == ["claims-north_west-2025-12-01"]
    assert recorded.configuration_versions.model_name == settings.model_name
    assert (
        recorded.configuration_versions.max_price_movement_pct
        == settings.policy.max_price_movement_pct
    )
    assert recorded.configuration_versions.prompt_version
    assert recorded.configuration_versions.agent_registry_version
    assert recorded.configuration_versions.tool_version
    assert recorded.configuration_versions.dataset_version
    assert recorded.configuration_versions.recommendation_policy_version
    assert store.get(recorded.record_id) == recorded


def test_record_decision_rejects_missing_rationale(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    with pytest.raises(ValidationError, match="rationale is required"):
        record_analyst_decision(_request(AnalystDecisionType.APPROVE, "   "), Settings(), store)


def test_record_decision_rejects_conditions_missing_for_approve_with_conditions(
    tmp_path: Path,
) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    with pytest.raises(ValidationError, match="requires at least one"):
        record_analyst_decision(
            _request(AnalystDecisionType.APPROVE_WITH_CONDITIONS, "Approve but constrain."),
            Settings(),
            store,
        )


def test_recorded_decision_preserves_the_replay_source(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    settings = Settings()

    recorded = record_analyst_decision(
        _request(
            AnalystDecisionType.APPROVE,
            "Evidence supports the recommendation.",
            source=ResultSource.REPLAY,
        ),
        settings,
        store,
    )

    assert recorded.source is ResultSource.REPLAY
    assert store.get(recorded.record_id).source is ResultSource.REPLAY


def test_replaying_an_analysis_never_creates_a_decision_record_by_itself(tmp_path: Path) -> None:
    from pricing_copilot.replay.pipeline import run_replay_portfolio_workflow
    from pricing_copilot.contracts import AnalysisPeriod as _AnalysisPeriod
    from pricing_copilot.contracts import PortfolioQuestion as _PortfolioQuestion

    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    replay_settings = Settings(replay_directory=tmp_path / "replay")
    question = _PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=_AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.RETENTION_CONCERN,
    )

    from pricing_copilot.replay.store import ReplayArtifactMissingError

    with pytest.raises(ReplayArtifactMissingError):
        run_replay_portfolio_workflow(question, replay_settings)

    assert store.list_for_question(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL) == []

    record_analyst_decision(
        _request(AnalystDecisionType.APPROVE, "Explicit approval."), Settings(), store
    )
    assert (
        len(store.list_for_question(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL))
        == 1
    )
