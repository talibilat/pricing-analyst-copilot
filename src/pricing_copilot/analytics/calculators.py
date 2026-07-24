from __future__ import annotations

from datetime import date

from pricing_copilot.analytics.contracts import (
    ClaimsMetrics,
    CompetitorMetrics,
    CompetitorMovement,
    ConversionMetrics,
    MonthlyValue,
    PricingHistoryComparison,
    WindowMetric,
)
from pricing_copilot.contracts import Segment
from pricing_copilot.data.records import (
    ClaimsMonthlyRecord,
    CompetitorMonthlyRecord,
    ConversionMonthlyRecord,
    PricingActionRecord,
)

BASELINE_WINDOW_MONTHS = 12
TOTAL_MONTHS = 24
MAX_PLAUSIBLE_LOSS_RATIO = 5.0
MAX_PLAUSIBLE_PRICE_CHANGE_PCT = 25.0


class MetricCalculationError(ValueError):
    """Raised when input data cannot produce a reliable deterministic metric."""


def _expected_periods(start: date, count: int) -> list[date]:
    periods: list[date] = []
    year, month = start.year, start.month
    for _ in range(count):
        periods.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def _require_complete_monthly_series(periods: list[date], domain: str) -> None:
    if len(periods) != TOTAL_MONTHS:
        raise MetricCalculationError(
            f"{domain}: expected {TOTAL_MONTHS} monthly periods, got {len(periods)}."
        )
    if periods != _expected_periods(periods[0], TOTAL_MONTHS):
        raise MetricCalculationError(f"{domain}: monthly periods are not a contiguous series.")


def _window_metric(monthly: list[MonthlyValue]) -> WindowMetric:
    baseline_values = [m.value for m in monthly[:BASELINE_WINDOW_MONTHS]]
    current_values = [m.value for m in monthly[BASELINE_WINDOW_MONTHS:]]
    baseline = sum(baseline_values) / len(baseline_values)
    current = sum(current_values) / len(current_values)
    movement_pct = None if baseline == 0 else (current - baseline) / baseline * 100
    return WindowMetric(
        baseline=baseline, current=current, movement_pct=movement_pct, monthly=monthly
    )


def calculate_claims_metrics(records: list[ClaimsMonthlyRecord]) -> ClaimsMetrics:
    ordered = sorted(records, key=lambda r: r.period)
    _require_complete_monthly_series([r.period for r in ordered], "claims")

    frequency_monthly: list[MonthlyValue] = []
    severity_monthly: list[MonthlyValue] = []
    incurred_loss_monthly: list[MonthlyValue] = []
    loss_ratio_monthly: list[MonthlyValue] = []

    for record in ordered:
        label = record.period.isoformat()
        if record.policies_in_force <= 0:
            raise MetricCalculationError(
                f"claims: policies_in_force must be positive for {label}."
            )
        if record.claim_count < 0:
            raise MetricCalculationError(f"claims: claim_count cannot be negative for {label}.")
        if record.claim_count == 0:
            raise MetricCalculationError(
                f"claims: cannot compute severity with zero claims for {label}."
            )
        if record.earned_premium_gbp <= 0:
            raise MetricCalculationError(
                f"claims: earned_premium_gbp must be positive for {label}."
            )
        if record.incurred_loss_gbp < 0:
            raise MetricCalculationError(
                f"claims: incurred_loss_gbp cannot be negative for {label}."
            )

        loss_ratio = record.incurred_loss_gbp / record.earned_premium_gbp
        if loss_ratio > MAX_PLAUSIBLE_LOSS_RATIO:
            raise MetricCalculationError(
                f"claims: loss ratio {loss_ratio:.2f} for {label} is an implausible extreme value."
            )

        frequency_monthly.append(
            MonthlyValue(
                period=record.period, value=record.claim_count / record.policies_in_force
            )
        )
        severity_monthly.append(
            MonthlyValue(period=record.period, value=record.incurred_loss_gbp / record.claim_count)
        )
        incurred_loss_monthly.append(
            MonthlyValue(period=record.period, value=record.incurred_loss_gbp)
        )
        loss_ratio_monthly.append(MonthlyValue(period=record.period, value=loss_ratio))

    return ClaimsMetrics(
        period_start=ordered[0].period,
        period_end=ordered[-1].period,
        claim_frequency=_window_metric(frequency_monthly),
        average_severity_gbp=_window_metric(severity_monthly),
        incurred_loss_gbp=_window_metric(incurred_loss_monthly),
        loss_ratio=_window_metric(loss_ratio_monthly),
    )


def calculate_conversion_metrics(
    records: list[ConversionMonthlyRecord], primary_segment: Segment
) -> ConversionMetrics:
    primary_records = sorted(
        (r for r in records if r.segment == primary_segment), key=lambda r: r.period
    )
    _require_complete_monthly_series([r.period for r in primary_records], "conversion")

    conversion_monthly: list[MonthlyValue] = []
    retention_monthly: list[MonthlyValue] = []
    premium_monthly: list[MonthlyValue] = []

    for record in primary_records:
        label = record.period.isoformat()
        if record.quotes <= 0:
            raise MetricCalculationError(f"conversion: quotes must be positive for {label}.")
        if record.sales < 0 or record.sales > record.quotes:
            raise MetricCalculationError(f"conversion: sales out of range for {label}.")
        if record.renewals_due < 0:
            raise MetricCalculationError(
                f"conversion: renewals_due cannot be negative for {label}."
            )
        if record.renewals_retained < 0 or record.renewals_retained > record.renewals_due:
            raise MetricCalculationError(
                f"conversion: renewals_retained out of range for {label}."
            )
        if record.average_quoted_premium_gbp <= 0:
            raise MetricCalculationError(
                f"conversion: average premium must be positive for {label}."
            )
        if record.renewals_due == 0:
            raise MetricCalculationError(
                f"conversion: cannot compute retention with zero renewals due for {label}."
            )

        conversion_monthly.append(
            MonthlyValue(period=record.period, value=record.sales / record.quotes)
        )
        retention_monthly.append(
            MonthlyValue(period=record.period, value=record.renewals_retained / record.renewals_due)
        )
        premium_monthly.append(
            MonthlyValue(period=record.period, value=record.average_quoted_premium_gbp)
        )

    segment_groups: dict[Segment, list[ConversionMonthlyRecord]] = {}
    for record in records:
        segment_groups.setdefault(record.segment, []).append(record)

    segment_comparison: dict[str, WindowMetric] = {}
    for segment, rows in segment_groups.items():
        rows_sorted = sorted(rows, key=lambda r: r.period)
        _require_complete_monthly_series(
            [r.period for r in rows_sorted], f"conversion segment {segment.value}"
        )
        for row in rows_sorted:
            if row.quotes <= 0:
                raise MetricCalculationError(
                    f"conversion: quotes must be positive for segment {segment.value} "
                    f"in {row.period.isoformat()}."
                )
        segment_comparison[segment.value] = _window_metric(
            [MonthlyValue(period=r.period, value=r.sales / r.quotes) for r in rows_sorted]
        )

    return ConversionMetrics(
        period_start=primary_records[0].period,
        period_end=primary_records[-1].period,
        quote_to_sale_conversion=_window_metric(conversion_monthly),
        renewal_retention=_window_metric(retention_monthly),
        average_quoted_premium_gbp=_window_metric(premium_monthly),
        segment_comparison=segment_comparison,
    )


def calculate_competitor_metrics(records: list[CompetitorMonthlyRecord]) -> CompetitorMetrics:
    if not records:
        raise MetricCalculationError("competitors: no records provided.")

    by_competitor: dict[str, list[CompetitorMonthlyRecord]] = {}
    for record in records:
        if record.price_index <= 0:
            raise MetricCalculationError(
                f"competitors: price_index must be positive for {record.competitor_name} "
                f"in {record.period.isoformat()}."
            )
        by_competitor.setdefault(record.competitor_name, []).append(record)

    all_periods = sorted({r.period for r in records})
    _require_complete_monthly_series(all_periods, "competitors")

    by_period: dict[date, list[CompetitorMonthlyRecord]] = {}
    for record in records:
        by_period.setdefault(record.period, []).append(record)

    ranks: dict[str, dict[date, int]] = {}
    for period, rows in by_period.items():
        for rank, row in enumerate(sorted(rows, key=lambda r: r.price_index), start=1):
            ranks.setdefault(row.competitor_name, {})[period] = rank

    movements = []
    for name, rows in by_competitor.items():
        rows_sorted = sorted(rows, key=lambda r: r.period)
        _require_complete_monthly_series([r.period for r in rows_sorted], f"competitor {name}")
        index_monthly = [MonthlyValue(period=r.period, value=r.price_index) for r in rows_sorted]
        rank_monthly = [
            MonthlyValue(period=r.period, value=float(ranks[name][r.period])) for r in rows_sorted
        ]
        movements.append(
            CompetitorMovement(
                competitor_name=name,
                price_index=_window_metric(index_monthly),
                rank=_window_metric(rank_monthly),
            )
        )

    return CompetitorMetrics(
        period_start=all_periods[0],
        period_end=all_periods[-1],
        competitors=sorted(movements, key=lambda m: m.competitor_name),
    )


def summarize_pricing_history(records: list[PricingActionRecord]) -> list[PricingHistoryComparison]:
    ordered = sorted(records, key=lambda r: r.period)
    comparisons = []
    for record in ordered:
        if not record.rationale.strip():
            raise MetricCalculationError(
                f"pricing_history: rationale is required for action on {record.period.isoformat()}."
            )
        if abs(record.price_change_pct) > MAX_PLAUSIBLE_PRICE_CHANGE_PCT:
            raise MetricCalculationError(
                f"pricing_history: price_change_pct {record.price_change_pct} for "
                f"{record.period.isoformat()} is an implausible extreme value."
            )
        comparisons.append(
            PricingHistoryComparison(
                period=record.period,
                price_change_pct=record.price_change_pct,
                rationale=record.rationale,
                conversion_impact_pct=record.conversion_impact_pct,
                loss_ratio_impact_pct=record.loss_ratio_impact_pct,
            )
        )
    return comparisons
