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
    Segment,
)
from pricing_copilot.decisions.service import record_analyst_decision
from pricing_copilot.decisions.store import DecisionStore


def _request(
    decision: AnalystDecisionType, rationale: str, conditions: list[str] | None = None
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
