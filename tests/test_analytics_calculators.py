from datetime import date

import pytest

from pricing_copilot.analytics.calculators import (
    MetricCalculationError,
    calculate_claims_metrics,
    calculate_competitor_metrics,
    calculate_conversion_metrics,
    summarize_pricing_history,
)
from pricing_copilot.contracts import Product, Region, Segment
from pricing_copilot.data.records import (
    ClaimsMonthlyRecord,
    CompetitorMonthlyRecord,
    ConversionMonthlyRecord,
    PricingActionRecord,
)


def _periods(count: int = 24) -> list[date]:
    periods = []
    year, month = 2024, 1
    for _ in range(count):
        periods.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def _claims_records(periods: list[date], claim_count: int = 40) -> list[ClaimsMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        severity = 290.0 if index >= 12 else 250.0
        records.append(
            ClaimsMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                policies_in_force=1000,
                claim_count=claim_count,
                incurred_loss_gbp=claim_count * severity,
                earned_premium_gbp=50_000.0,
            )
        )
    return records


def test_claims_metrics_exact_movements() -> None:
    metrics = calculate_claims_metrics(_claims_records(_periods()))

    assert metrics.claim_frequency.baseline == pytest.approx(0.04)
    assert metrics.claim_frequency.movement_pct == pytest.approx(0.0)

    assert metrics.average_severity_gbp.baseline == pytest.approx(250.0)
    assert metrics.average_severity_gbp.current == pytest.approx(290.0)
    assert metrics.average_severity_gbp.movement_pct == pytest.approx(16.0)

    assert metrics.loss_ratio.baseline == pytest.approx(0.20)
    assert metrics.loss_ratio.current == pytest.approx(0.232)
    assert metrics.loss_ratio.movement_pct == pytest.approx(16.0)

    assert metrics.incurred_loss_gbp.movement_pct == pytest.approx(16.0)
    assert metrics.period_start == _periods()[0]
    assert metrics.period_end == _periods()[-1]


def test_claims_metrics_rejects_zero_claim_count() -> None:
    records = _claims_records(_periods())
    records[0] = records[0].model_copy(update={"claim_count": 0})
    with pytest.raises(MetricCalculationError, match="zero claims"):
        calculate_claims_metrics(records)


def test_claims_metrics_rejects_incomplete_periods() -> None:
    records = _claims_records(_periods())[:23]
    with pytest.raises(MetricCalculationError, match="expected 24"):
        calculate_claims_metrics(records)


def test_claims_metrics_rejects_negative_incurred_loss() -> None:
    records = _claims_records(_periods())
    records[0] = records[0].model_copy(update={"incurred_loss_gbp": -100.0})
    with pytest.raises(MetricCalculationError, match="cannot be negative"):
        calculate_claims_metrics(records)


def test_claims_metrics_rejects_extreme_loss_ratio() -> None:
    records = _claims_records(_periods())
    records[0] = records[0].model_copy(update={"incurred_loss_gbp": 500_000.0})
    with pytest.raises(MetricCalculationError, match="extreme value"):
        calculate_claims_metrics(records)


def _conversion_records(periods: list[date]) -> list[ConversionMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_current = index >= 12
        records.append(
            ConversionMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                quotes=1000,
                sales=180 if is_current else 200,
                renewals_due=500,
                renewals_retained=405 if is_current else 450,
                average_quoted_premium_gbp=660.0 if is_current else 600.0,
            )
        )
        records.append(
            ConversionMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.NEW_BUSINESS,
                quotes=800,
                sales=120,
                renewals_due=0,
                renewals_retained=0,
                average_quoted_premium_gbp=550.0,
            )
        )
    return records


def test_conversion_metrics_exact_movements() -> None:
    metrics = calculate_conversion_metrics(_conversion_records(_periods()), Segment.RENEWAL)

    assert metrics.quote_to_sale_conversion.baseline == pytest.approx(0.20)
    assert metrics.quote_to_sale_conversion.movement_pct == pytest.approx(-10.0)
    assert metrics.renewal_retention.movement_pct == pytest.approx(-10.0)
    assert metrics.average_quoted_premium_gbp.movement_pct == pytest.approx(10.0)

    assert metrics.segment_comparison["renewal"].baseline == pytest.approx(0.20)
    assert metrics.segment_comparison["new_business"].baseline == pytest.approx(0.15)
    assert metrics.segment_comparison["new_business"].movement_pct == pytest.approx(0.0)


def test_conversion_metrics_rejects_zero_quotes() -> None:
    records = _conversion_records(_periods())
    records[0] = records[0].model_copy(update={"quotes": 0})
    with pytest.raises(MetricCalculationError, match="quotes must be positive"):
        calculate_conversion_metrics(records, Segment.RENEWAL)


def test_conversion_metrics_rejects_sales_above_quotes() -> None:
    records = _conversion_records(_periods())
    records[0] = records[0].model_copy(update={"sales": 5000})
    with pytest.raises(MetricCalculationError, match="out of range"):
        calculate_conversion_metrics(records, Segment.RENEWAL)


def _competitor_records(periods: list[date]) -> list[CompetitorMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_current = index >= 12
        records.append(
            CompetitorMonthlyRecord(
                period=period,
                region=Region.NORTH_WEST,
                competitor_name="Test Insurer A",
                price_index=110.0 if is_current else 100.0,
            )
        )
        records.append(
            CompetitorMonthlyRecord(
                period=period,
                region=Region.NORTH_WEST,
                competitor_name="Test Insurer B",
                price_index=99.0 if is_current else 90.0,
            )
        )
    return records


def test_competitor_metrics_exact_index_and_stable_rank() -> None:
    metrics = calculate_competitor_metrics(_competitor_records(_periods()))
    by_name = {m.competitor_name: m for m in metrics.competitors}

    assert by_name["Test Insurer A"].price_index.movement_pct == pytest.approx(10.0)
    assert by_name["Test Insurer B"].price_index.movement_pct == pytest.approx(10.0)
    assert by_name["Test Insurer A"].rank.baseline == pytest.approx(2.0)
    assert by_name["Test Insurer B"].rank.baseline == pytest.approx(1.0)
    assert by_name["Test Insurer A"].rank.movement_pct == pytest.approx(0.0)


def test_competitor_metrics_rejects_non_positive_price_index() -> None:
    records = _competitor_records(_periods())
    records[0] = records[0].model_copy(update={"price_index": 0.0})
    with pytest.raises(MetricCalculationError, match="must be positive"):
        calculate_competitor_metrics(records)


def test_summarize_pricing_history_passes_through_and_orders() -> None:
    action = PricingActionRecord(
        period=date(2024, 6, 1),
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        price_change_pct=2.0,
        rationale="Test rationale",
        conversion_impact_pct=-0.5,
        loss_ratio_impact_pct=-1.0,
    )
    comparisons = summarize_pricing_history([action])
    assert len(comparisons) == 1
    assert comparisons[0].price_change_pct == 2.0
    assert comparisons[0].rationale == "Test rationale"


def test_summarize_pricing_history_rejects_empty_rationale() -> None:
    action = PricingActionRecord(
        period=date(2024, 6, 1),
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        price_change_pct=2.0,
        rationale="   ",
        conversion_impact_pct=-0.5,
        loss_ratio_impact_pct=-1.0,
    )
    with pytest.raises(MetricCalculationError, match="rationale is required"):
        summarize_pricing_history([action])


def test_summarize_pricing_history_rejects_extreme_price_change() -> None:
    action = PricingActionRecord(
        period=date(2024, 6, 1),
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        price_change_pct=40.0,
        rationale="Implausible jump",
        conversion_impact_pct=-0.5,
        loss_ratio_impact_pct=-1.0,
    )
    with pytest.raises(MetricCalculationError, match="extreme value"):
        summarize_pricing_history([action])
