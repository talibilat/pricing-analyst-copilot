from datetime import date

import pytest

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    Product,
    RecommendationAction,
    Region,
    Segment,
)
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


def test_unsupported_question_is_rejected_with_clear_message() -> None:
    with pytest.raises(UnsupportedPortfolioError) as exc_info:
        run_portfolio_workflow(_question(region=Region.SOUTH_EAST))
    assert "south_east" in str(exc_info.value)
