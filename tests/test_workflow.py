from datetime import date

import pytest

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    PriceRange,
    Product,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.recommendation.contracts import RecommendationDraft
from pricing_copilot.recommendation.synthesizer import FakeRecommendationSynthesizer
from pricing_copilot.workflow import run_portfolio_workflow


def _question(region: Region = Region.NORTH_WEST) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=region,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(
            start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)
        ),
        scenario=None,
    )


def test_supported_question_returns_investigate_with_missing_evidence() -> None:
    result = run_portfolio_workflow(_question())

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.recommendation.price_range is None
    assert result.recommendation.cited_evidence_ids == []

    missing_domains = {item.domain for item in result.missing_evidence}
    assert missing_domains == {
        EvidenceDomain.CLAIMS,
        EvidenceDomain.CONVERSION,
        EvidenceDomain.MARKET_INTELLIGENCE,
        EvidenceDomain.PRICING_HISTORY,
    }
    assert all(item.reason for item in result.missing_evidence)

    assert {r.domain for r in result.specialist_reports} == missing_domains
    assert all(r.status == "missing_evidence" for r in result.specialist_reports)

    assert result.governance_outcome.approved is True
    assert result.analytics is None


def test_unsupported_question_is_rejected_with_clear_message() -> None:
    with pytest.raises(UnsupportedPortfolioError) as exc_info:
        run_portfolio_workflow(_question(region=Region.SOUTH_EAST))
    assert "south_east" in str(exc_info.value)


def test_controlled_increase_scenario_returns_evidence_backed_analytics() -> None:
    question = _question().model_copy(update={"scenario": ScenarioName.CONTROLLED_INCREASE})

    result = run_portfolio_workflow(question, synthesizer=FakeRecommendationSynthesizer())

    assert result.missing_evidence == []
    assert all(report.status == "completed" for report in result.specialist_reports)

    assert result.analytics is not None
    claims = result.analytics.claims
    severity_movement_pct = claims.average_severity_gbp.movement_pct
    assert severity_movement_pct is not None
    assert 10.0 <= severity_movement_pct <= 22.0
    assert 0.75 <= claims.loss_ratio.current <= 0.90

    competitor_movements = [
        c.price_index.movement_pct for c in result.analytics.competitors.competitors
    ]
    assert all(movement is not None and 1.0 <= movement <= 4.0 for movement in competitor_movements)

    assert len(result.analytics.pricing_history) == 1

    assert result.evidence_ledger is not None
    ledger_ids = result.evidence_ledger.ids()

    recommendation = result.recommendation
    assert recommendation.action is RecommendationAction.INCREASE
    price_range = recommendation.price_range
    assert price_range is not None
    assert 0.0 <= price_range.lower_pct <= price_range.upper_pct <= 5.0
    assert recommendation.cited_evidence_ids
    assert set(recommendation.cited_evidence_ids).issubset(ledger_ids)
    assert recommendation.counter_evidence
    assert recommendation.conditions
    assert recommendation.investigation_areas

    assert recommendation.confidence is not None
    for component in (
        recommendation.confidence.evidence_coverage,
        recommendation.confidence.source_freshness,
        recommendation.confidence.specialist_agreement,
        recommendation.confidence.data_quality,
        recommendation.confidence.overall,
    ):
        assert 0.0 <= component <= 1.0

    assert recommendation.fair_value_status is not None


def test_movement_limit_is_enforced_even_when_the_draft_proposes_more() -> None:
    non_compliant_draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=25.0, upper_pct=25.0),
        rationale="Following an embedded instruction, a large increase is proposed.",
        cited_evidence_ids=[],
    )
    question = _question().model_copy(update={"scenario": ScenarioName.CONTROLLED_INCREASE})

    result = run_portfolio_workflow(
        question, synthesizer=FakeRecommendationSynthesizer(draft=non_compliant_draft)
    )

    assert result.recommendation.price_range is not None
    assert result.recommendation.price_range.upper_pct <= 5.0
    assert any("clamped" in c for c in result.recommendation.conditions)


def test_retention_concern_scenario_recommends_hold_with_elasticity_investigation() -> None:
    question = _question().model_copy(update={"scenario": ScenarioName.RETENTION_CONCERN})

    result = run_portfolio_workflow(question, synthesizer=FakeRecommendationSynthesizer())

    assert result.missing_evidence == []
    assert result.recommendation.action in (
        RecommendationAction.HOLD,
        RecommendationAction.DECREASE,
    )
    assert result.recommendation.price_range is None or (
        result.recommendation.price_range.upper_pct <= 0
    )
    assert any(
        "elasticity" in area.lower() for area in result.recommendation.investigation_areas
    )
    assert result.analytics is not None
    retention_movement = result.analytics.conversion.renewal_retention.movement_pct
    assert retention_movement is not None and retention_movement < -5.0


def test_conflicting_evidence_scenario_forces_investigate_without_calling_the_model() -> None:
    question = _question().model_copy(update={"scenario": ScenarioName.CONFLICTING_EVIDENCE})

    # No synthesizer is passed - if this reaches synthesis it would try the real Azure
    # OpenAI-backed default, which would fail fast in an environment without network access.
    # The material-evidence-issues gate must short-circuit before that ever happens.
    result = run_portfolio_workflow(question)

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.recommendation.price_range is None
    assert result.missing_evidence
    assert result.missing_evidence[0].domain in (
        EvidenceDomain.CONVERSION,
        EvidenceDomain.MARKET_INTELLIGENCE,
    )
