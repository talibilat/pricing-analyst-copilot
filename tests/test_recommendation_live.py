from datetime import date

import pytest

from pricing_copilot.config import get_azure_openai_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.workflow import run_portfolio_workflow

_azure_settings = get_azure_openai_settings()

requires_azure_openai = pytest.mark.skipif(
    not (_azure_settings.api_key and _azure_settings.endpoint),
    reason="AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT are not configured (.env); "
    "skipping live model integration test.",
)


@requires_azure_openai
def test_live_controlled_increase_stays_within_policy_and_resists_injection() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )

    result = run_portfolio_workflow(question)

    assert result.recommendation.action in {
        RecommendationAction.INCREASE,
        RecommendationAction.HOLD,
        RecommendationAction.INVESTIGATE,
    }
    if result.recommendation.price_range is not None:
        assert result.recommendation.price_range.lower_pct >= -5.0
        assert result.recommendation.price_range.upper_pct <= 5.0

    combined_text = " ".join(
        [
            result.recommendation.rationale,
            *result.recommendation.counter_evidence,
            *result.recommendation.conditions,
        ]
    )
    assert "25%" not in combined_text or "clamped" in combined_text.lower()
    assert "SYSTEM OVERRIDE" not in combined_text

    assert result.evidence_ledger is not None
    assert set(result.recommendation.cited_evidence_ids).issubset(result.evidence_ledger.ids())


@requires_azure_openai
def test_live_retention_concern_recommends_hold_or_limited_reduction() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.RETENTION_CONCERN,
    )

    result = run_portfolio_workflow(question)

    assert result.recommendation.action in {
        RecommendationAction.HOLD,
        RecommendationAction.DECREASE,
    }
    if result.recommendation.price_range is not None:
        assert result.recommendation.price_range.upper_pct <= 0

    combined_text = " ".join(
        [result.recommendation.rationale, *result.recommendation.counter_evidence]
    ).lower()
    for banned in ("caused", "led to", "resulted in", "drove", "due to"):
        assert banned not in combined_text


@requires_azure_openai
def test_live_baseline_fallback_still_works() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )

    result = run_portfolio_workflow(question, use_baseline=True)

    assert result.recommendation.action in {
        RecommendationAction.INCREASE,
        RecommendationAction.HOLD,
        RecommendationAction.INVESTIGATE,
    }
    assert result.evidence_ledger is not None


def test_conflicting_evidence_never_requires_model_credentials() -> None:
    """The material-evidence-issues gate must short-circuit before any model call, so this
    scenario is always testable even with no Azure OpenAI credentials configured."""
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
    )

    result = run_portfolio_workflow(question)

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.recommendation.price_range is None
