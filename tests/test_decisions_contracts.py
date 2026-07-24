from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecision,
    AnalystDecisionType,
    ConfigurationVersions,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)


def _question() -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=None,
    )


def _versions() -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name="gpt-5.4",
        recommendation_version="single-agent-baseline-v1",
        governance_version="deterministic-governance-v1",
        scenario_seed=20260101,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )


def _base_kwargs() -> dict:
    return dict(
        question=_question(),
        recommendation=Recommendation(action=RecommendationAction.INCREASE, rationale="test"),
        governance_outcome=GovernanceOutcome(approved=True),
        evidence_ids=["claims-north_west-2025-12-01"],
        configuration_versions=_versions(),
        decided_at=datetime.now(UTC),
    )


def test_approve_requires_no_conditions() -> None:
    decision = AnalystDecision(
        decision=AnalystDecisionType.APPROVE, rationale="Evidence is sufficient.", **_base_kwargs()
    )
    assert decision.conditions == []


def test_reject_requires_no_conditions() -> None:
    decision = AnalystDecision(
        decision=AnalystDecisionType.REJECT, rationale="Not convinced by the evidence.", **_base_kwargs()
    )
    assert decision.decision is AnalystDecisionType.REJECT


def test_empty_rationale_is_rejected() -> None:
    with pytest.raises(ValidationError, match="rationale is required"):
        AnalystDecision(decision=AnalystDecisionType.APPROVE, rationale="   ", **_base_kwargs())


def test_approve_with_conditions_requires_conditions() -> None:
    with pytest.raises(ValidationError, match="requires at least one"):
        AnalystDecision(
            decision=AnalystDecisionType.APPROVE_WITH_CONDITIONS,
            rationale="Approve but constrain rollout.",
            conditions=[],
            **_base_kwargs(),
        )


def test_approve_with_conditions_accepts_explicit_conditions() -> None:
    decision = AnalystDecision(
        decision=AnalystDecisionType.APPROVE_WITH_CONDITIONS,
        rationale="Approve but constrain rollout.",
        conditions=["Limit to pilot cohort for the first cycle."],
        **_base_kwargs(),
    )
    assert decision.conditions == ["Limit to pilot cohort for the first cycle."]


def test_request_investigation_requires_outstanding_questions() -> None:
    with pytest.raises(ValidationError, match="requires at least one"):
        AnalystDecision(
            decision=AnalystDecisionType.REQUEST_INVESTIGATION,
            rationale="Need more evidence before deciding.",
            conditions=[],
            **_base_kwargs(),
        )
