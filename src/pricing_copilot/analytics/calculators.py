from __future__ import annotations

from datetime import date
from typing import Protocol

from pricing_copilot.analytics.contracts import (
    ClaimsMetrics,
    CompetitorMetrics,
    CompetitorMovement,
    ConversionMetrics,
    MonthlyValue,
    PricingHistoryComparison,
    WindowMetric,
)
from pricing_copilot.contracts import AnalysisPeriod, Segment
from pricing_copilot.data.records import (
    ClaimsMonthlyRecord,
    CompetitorMonthlyRecord,
    ConversionMonthlyRecord,
    PricingActionRecord,
)

MAX_PLAUSIBLE_LOSS_RATIO = 5.0
MAX_PLAUSIBLE_PRICE_CHANGE_PCT = 25.0


class MetricCalculationError(ValueError):
    """Raised when input data cannot produce a reliable deterministic metric."""


class _DatedRecord(Protocol):
    period: date


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


def _require_contiguous_monthly_series(periods: list[date], domain: str) -> None:
    if not periods:
        raise MetricCalculationError(f"{domain}: no monthly periods were provided.")
    if periods != _expected_periods(periods[0], len(periods)):
        raise MetricCalculationError(f"{domain}: monthly periods are not a contiguous series.")


def _window_metric(
    current_monthly: list[MonthlyValue],
    baseline_monthly: list[MonthlyValue] | None = None,
    *,
    expected_periods: int | None = None,
) -> WindowMetric:
    baseline_values = [m.value for m in baseline_monthly or []]
    current_values = [m.value for m in current_monthly]
    baseline = sum(baseline_values) / len(baseline_values) if baseline_values else None
    current = sum(current_values) / len(current_values)
    movement_pct = None if baseline in (None, 0) else (current - baseline) / baseline * 100
    return WindowMetric(
        baseline=baseline,
        current=current,
        movement_pct=movement_pct,
        monthly=current_monthly,
        observed_periods=len(current_monthly),
        expected_periods=expected_periods,
    )


def _months_inclusive(period: AnalysisPeriod) -> int:
    return (
        (period.end_month.year - period.start_month.year) * 12
        + (period.end_month.month - period.start_month.month)
        + 1
    )


def _window_records[T: _DatedRecord](
    records: list[T], *, period: AnalysisPeriod | None, domain: str
) -> tuple[list[T], list[T], int | None]:
    """Return current and comparable prior records without imposing a 24-month requirement.

    For an explicit request, the current window may be incomplete at its end.  The caller still
    receives the contiguous observed portion and an equal-length prior comparison.  That makes
    the missing months visible through ``WindowMetric.is_complete`` instead of turning a useful
    answer into a hard failure.
    """
    ordered = sorted(records, key=lambda record: record.period)
    if period is None:
        _require_contiguous_monthly_series([record.period for record in ordered], domain)
        if len(ordered) < 2:
            raise MetricCalculationError(f"{domain}: at least two monthly periods are required.")
        split = len(ordered) // 2
        return ordered[split:], ordered[:split], None

    expected = _months_inclusive(period)
    current = [
        record for record in ordered if period.start_month <= record.period <= period.end_month
    ]
    if not current:
        raise MetricCalculationError(
            f"{domain}: no data is available for {period.start_month.isoformat()} to "
            f"{period.end_month.isoformat()}."
        )
    _require_contiguous_monthly_series([record.period for record in current], domain)
    if current[0].period != period.start_month:
        raise MetricCalculationError(
            f"{domain}: data does not start at the requested period "
            f"{period.start_month.isoformat()}."
        )
    current_count = len(current)
    prior = [record for record in ordered if record.period < period.start_month]
    baseline = prior[-current_count:]
    if len(baseline) == current_count:
        _require_contiguous_monthly_series([record.period for record in baseline], domain)
    else:
        baseline = []
    return current, baseline, expected


def calculate_claims_metrics(
    records: list[ClaimsMonthlyRecord], analysis_period: AnalysisPeriod | None = None
) -> ClaimsMetrics:
    all_records = sorted(records, key=lambda record: record.period)
    ordered, baseline_records, expected_periods = _window_records(
        records, period=analysis_period, domain="claims"
    )

    frequency_monthly: list[MonthlyValue] = []
    severity_monthly: list[MonthlyValue] = []
    incurred_loss_monthly: list[MonthlyValue] = []
    loss_ratio_monthly: list[MonthlyValue] = []

    def metrics_for(
        records_to_measure: list[ClaimsMonthlyRecord],
    ) -> tuple[list[MonthlyValue], list[MonthlyValue], list[MonthlyValue], list[MonthlyValue]]:
        frequency: list[MonthlyValue] = []
        severity: list[MonthlyValue] = []
        incurred_loss: list[MonthlyValue] = []
        loss_ratio_values: list[MonthlyValue] = []
        for record in records_to_measure:
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
                    f"claims: loss ratio {loss_ratio:.2f} for {label} is an implausible "
                    "extreme value."
                )

            frequency.append(
                MonthlyValue(
                    period=record.period, value=record.claim_count / record.policies_in_force
                )
            )
            severity.append(
                MonthlyValue(
                    period=record.period, value=record.incurred_loss_gbp / record.claim_count
                )
            )
            incurred_loss.append(MonthlyValue(period=record.period, value=record.incurred_loss_gbp))
            loss_ratio_values.append(MonthlyValue(period=record.period, value=loss_ratio))
        return frequency, severity, incurred_loss, loss_ratio_values

    frequency_monthly, severity_monthly, incurred_loss_monthly, loss_ratio_monthly = metrics_for(
        ordered
    )
    (
        baseline_frequency,
        baseline_severity,
        baseline_incurred_loss,
        baseline_loss_ratio,
    ) = metrics_for(baseline_records)

    return ClaimsMetrics(
        period_start=(all_records[0] if analysis_period is None else ordered[0]).period,
        period_end=(all_records[-1] if analysis_period is None else ordered[-1]).period,
        claim_frequency=_window_metric(
            frequency_monthly, baseline_frequency, expected_periods=expected_periods
        ),
        average_severity_gbp=_window_metric(
            severity_monthly, baseline_severity, expected_periods=expected_periods
        ),
        incurred_loss_gbp=_window_metric(
            incurred_loss_monthly, baseline_incurred_loss, expected_periods=expected_periods
        ),
        loss_ratio=_window_metric(
            loss_ratio_monthly, baseline_loss_ratio, expected_periods=expected_periods
        ),
    )


def calculate_conversion_metrics(
    records: list[ConversionMonthlyRecord],
    primary_segment: Segment,
    analysis_period: AnalysisPeriod | None = None,
) -> ConversionMetrics:
    primary_records, primary_baseline, expected_periods = _window_records(
        [record for record in records if record.segment == primary_segment],
        period=analysis_period,
        domain="conversion",
    )

    def metrics_for(
        records_to_measure: list[ConversionMonthlyRecord],
    ) -> tuple[list[MonthlyValue], list[MonthlyValue], list[MonthlyValue]]:
        conversion: list[MonthlyValue] = []
        retention: list[MonthlyValue] = []
        premium: list[MonthlyValue] = []
        for record in records_to_measure:
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
            conversion.append(
                MonthlyValue(period=record.period, value=record.sales / record.quotes)
            )
            retention.append(
                MonthlyValue(
                    period=record.period, value=record.renewals_retained / record.renewals_due
                )
            )
            premium.append(
                MonthlyValue(period=record.period, value=record.average_quoted_premium_gbp)
            )
        return conversion, retention, premium

    conversion_monthly, retention_monthly, premium_monthly = metrics_for(primary_records)
    baseline_conversion, baseline_retention, baseline_premium = metrics_for(primary_baseline)

    segment_groups: dict[Segment, list[ConversionMonthlyRecord]] = {}
    for record in records:
        segment_groups.setdefault(record.segment, []).append(record)

    segment_comparison: dict[str, WindowMetric] = {}
    for segment, rows in segment_groups.items():
        rows_sorted, baseline_rows, segment_expected = _window_records(
            rows,
            period=analysis_period,
            domain=f"conversion segment {segment.value}",
        )
        for row in rows_sorted:
            if row.quotes <= 0:
                raise MetricCalculationError(
                    f"conversion: quotes must be positive for segment {segment.value} "
                    f"in {row.period.isoformat()}."
                )
        segment_comparison[segment.value] = _window_metric(
            [MonthlyValue(period=r.period, value=r.sales / r.quotes) for r in rows_sorted],
            [MonthlyValue(period=r.period, value=r.sales / r.quotes) for r in baseline_rows],
            expected_periods=segment_expected,
        )

    return ConversionMetrics(
        period_start=primary_records[0].period,
        period_end=primary_records[-1].period,
        quote_to_sale_conversion=_window_metric(
            conversion_monthly, baseline_conversion, expected_periods=expected_periods
        ),
        renewal_retention=_window_metric(
            retention_monthly, baseline_retention, expected_periods=expected_periods
        ),
        average_quoted_premium_gbp=_window_metric(
            premium_monthly, baseline_premium, expected_periods=expected_periods
        ),
        segment_comparison=segment_comparison,
    )


def calculate_competitor_metrics(
    records: list[CompetitorMonthlyRecord], analysis_period: AnalysisPeriod | None = None
) -> CompetitorMetrics:
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
    _require_contiguous_monthly_series(all_periods, "competitors")

    by_period: dict[date, list[CompetitorMonthlyRecord]] = {}
    for record in records:
        by_period.setdefault(record.period, []).append(record)

    ranks: dict[str, dict[date, int]] = {}
    for period, rows in by_period.items():
        for rank, row in enumerate(sorted(rows, key=lambda r: r.price_index), start=1):
            ranks.setdefault(row.competitor_name, {})[period] = rank

    movements = []
    for name, rows in by_competitor.items():
        rows_sorted, baseline_rows, expected_periods = _window_records(
            rows, period=analysis_period, domain=f"competitor {name}"
        )
        index_monthly = [MonthlyValue(period=r.period, value=r.price_index) for r in rows_sorted]
        baseline_index = [MonthlyValue(period=r.period, value=r.price_index) for r in baseline_rows]
        rank_monthly = [
            MonthlyValue(period=r.period, value=float(ranks[name][r.period])) for r in rows_sorted
        ]
        baseline_rank = [
            MonthlyValue(period=r.period, value=float(ranks[name][r.period])) for r in baseline_rows
        ]
        movements.append(
            CompetitorMovement(
                competitor_name=name,
                price_index=_window_metric(
                    index_monthly, baseline_index, expected_periods=expected_periods
                ),
                rank=_window_metric(rank_monthly, baseline_rank, expected_periods=expected_periods),
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
