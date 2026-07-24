from datetime import date

import pytest
from pydantic import ValidationError

from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    PriceRange,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)


def test_analysis_period_rejects_end_before_start():
    with pytest.raises(ValidationError):
        AnalysisPeriod(start_month=date(2026, 3, 1), end_month=date(2026, 1, 1))


def test_portfolio_question_round_trips():
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(
            start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)
        ),
        scenario=None,
    )
    assert question.model_dump()["product"] == "personal_motor"


def test_price_range_rejects_upper_below_lower():
    with pytest.raises(ValidationError):
        PriceRange(lower_pct=3.0, upper_pct=1.0)


def test_recommendation_requires_evidence_domain_enum():
    rec = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        price_range=None,
        rationale="No evidence connected yet.",
        cited_evidence_ids=[],
        confidence=None,
    )
    assert rec.action is RecommendationAction.INVESTIGATE
    assert EvidenceDomain.CLAIMS.value == "claims"
