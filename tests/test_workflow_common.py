from datetime import date

from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    Product,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.data.repository import PortfolioDataRepository
from pricing_copilot.workflow_common import (
    IMPLEMENTED_DATA_SCENARIOS,
    REQUIRED_EVIDENCE_DOMAINS,
    build_analytics,
    data_quality_investigation_result,
    missing_evidence_workflow_result,
)


def _question(scenario: ScenarioName | None = None) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)),
        scenario=scenario,
    )


def test_implemented_data_scenarios_covers_the_three_priceable_scenarios() -> None:
    assert IMPLEMENTED_DATA_SCENARIOS == {
        ScenarioName.CONTROLLED_INCREASE,
        ScenarioName.RETENTION_CONCERN,
        ScenarioName.CONFLICTING_EVIDENCE,
    }


def test_drift_monitoring_scenario_is_deliberately_not_priceable() -> None:
    assert ScenarioName.DRIFT_MONITORING not in IMPLEMENTED_DATA_SCENARIOS


def test_missing_evidence_workflow_result_investigates_with_all_domains_missing() -> None:
    result = missing_evidence_workflow_result(_question())
    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert {m.domain for m in result.missing_evidence} == set(REQUIRED_EVIDENCE_DOMAINS)


def test_data_quality_investigation_result_maps_conversion_prefix_to_conversion_domain() -> None:
    result = data_quality_investigation_result(_question(), "conversion: quotes must be positive.")
    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.missing_evidence[0].domain is EvidenceDomain.CONVERSION


def test_build_analytics_returns_populated_analytics_for_controlled_increase() -> None:
    question = _question(ScenarioName.CONTROLLED_INCREASE)
    repository = PortfolioDataRepository.from_scenario(ScenarioName.CONTROLLED_INCREASE)
    analytics = build_analytics(question, repository)
    assert analytics.claims.loss_ratio.current > 0
