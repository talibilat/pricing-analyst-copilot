from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.generation import DRIFT_CURRENT_INDEX, generate_feedback_topic_series
from pricing_copilot.data.persistent import PersistentAnalyticsDatabase
from pricing_copilot.drift.contracts import (
    DriftAlert,
    DriftAlertCategory,
    DriftDomain,
    DriftMeasureKind,
    DriftMeasurement,
)
from pricing_copilot.drift.statistics import (
    kolmogorov_smirnov,
    percentage_movement,
    population_stability_index,
    rolling_z_score,
)

BASELINE_START_INDEX = 12
BASELINE_END_INDEX = 24  # exclusive
BASELINE_WINDOW_LABEL = "months 13-24"
CURRENT_WINDOW_LABEL = "month 25"


def _insufficient_sample_alert(domain: DriftDomain, settings: Settings) -> DriftAlert:
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=domain.value,
        domain=domain,
        breached=False,
        investigation_required=False,
        insufficient_sample=True,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=(
            f"Fewer than {settings.drift.minimum_baseline_months} baseline months are available."
        ),
    )


def _z_and_movement_alert(
    *,
    domain: DriftDomain,
    baseline: list[float],
    current_value: float,
    unit: str,
    settings: Settings,
) -> DriftAlert:
    policy = settings.drift
    if len(baseline) < policy.minimum_baseline_months:
        return _insufficient_sample_alert(domain, settings)
    baseline_mean = sum(baseline) / len(baseline)
    z_score = rolling_z_score(baseline, current_value)
    movement = percentage_movement(baseline_mean, current_value)
    z_breached = abs(z_score) > policy.z_score_threshold
    movement_breached = abs(movement) > policy.percentage_movement_threshold_pct
    breached = z_breached or movement_breached
    measurements = [
        DriftMeasurement(
            measure_kind=DriftMeasureKind.ROLLING_Z_SCORE,
            value=round(z_score, 4),
            unit="standard deviations",
            threshold=policy.z_score_threshold,
            breached=z_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL}",
        ),
        DriftMeasurement(
            measure_kind=DriftMeasureKind.PERCENTAGE_MOVEMENT,
            value=round(movement, 2),
            unit="%",
            threshold=policy.percentage_movement_threshold_pct,
            breached=movement_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL}",
        ),
    ]
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=domain.value,
        domain=domain,
        measurements=measurements,
        breached=breached,
        investigation_required=breached,
        confidence_impact=0.4 if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=(
            f"{domain.value.replace('_', ' ').title()} moved {round(movement, 1)}% "
            f"({round(z_score, 2)} standard deviations) between {BASELINE_WINDOW_LABEL} and "
            f"{CURRENT_WINDOW_LABEL}, {unit} basis."
        ),
    )


def _claims_metrics(database: PersistentAnalyticsDatabase) -> tuple[list[float], list[float], list[float]]:
    result = database.query_source(
        "claims",
        ScenarioName.DRIFT_MONITORING,
        columns=(
            "period",
            "claim_count",
            "incurred_loss_gbp",
            "earned_premium_gbp",
            "policies_in_force",
        ),
    )
    rows = sorted(result.rows, key=lambda row: row[0])
    severities = [row[2] / row[1] for row in rows]
    frequencies = [row[1] / row[4] for row in rows]
    loss_ratios = [row[2] / row[3] for row in rows]
    return severities, frequencies, loss_ratios


def _conversion_metric(database: PersistentAnalyticsDatabase) -> list[float]:
    result = database.query_source(
        "conversion",
        ScenarioName.DRIFT_MONITORING,
        columns=("period", "quotes", "sales"),
    )
    rows = sorted(result.rows, key=lambda row: row[0])
    return [row[2] / row[1] for row in rows]


def _competitor_readings(
    database: PersistentAnalyticsDatabase,
) -> tuple[list[float], list[float], list[float], float]:
    result = database.query_source(
        "competitors", ScenarioName.DRIFT_MONITORING, columns=("period", "price_index")
    )
    rows = sorted(result.rows, key=lambda row: row[0])
    ordered_periods = sorted({row[0] for row in rows})
    by_period: dict = {period: [] for period in ordered_periods}
    for period, price_index in rows:
        by_period[period].append(price_index)

    baseline_periods = ordered_periods[BASELINE_START_INDEX:BASELINE_END_INDEX]
    current_period = ordered_periods[DRIFT_CURRENT_INDEX]
    baseline_all = [value for period in baseline_periods for value in by_period[period]]
    current_all = by_period[current_period]
    baseline_monthly_means = [
        sum(by_period[period]) / len(by_period[period]) for period in baseline_periods
    ]
    current_mean = sum(current_all) / len(current_all)
    return baseline_all, current_all, baseline_monthly_means, current_mean


def _competitor_alert(database: PersistentAnalyticsDatabase, settings: Settings) -> DriftAlert:
    baseline_all, current_all, baseline_monthly_means, current_mean = _competitor_readings(database)
    policy = settings.drift
    if len(baseline_monthly_means) < policy.minimum_baseline_months:
        return _insufficient_sample_alert(DriftDomain.COMPETITOR_INDEX, settings)

    movement = percentage_movement(
        sum(baseline_monthly_means) / len(baseline_monthly_means), current_mean
    )
    statistic, p_value = kolmogorov_smirnov(baseline_all, current_all)
    movement_breached = abs(movement) > policy.percentage_movement_threshold_pct
    ks_breached = p_value < policy.ks_p_value_threshold
    breached = movement_breached or ks_breached
    measurements = [
        DriftMeasurement(
            measure_kind=DriftMeasureKind.PERCENTAGE_MOVEMENT,
            value=round(movement, 2),
            unit="%",
            threshold=policy.percentage_movement_threshold_pct,
            breached=movement_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL}",
        ),
        DriftMeasurement(
            measure_kind=DriftMeasureKind.KOLMOGOROV_SMIRNOV,
            value=round(p_value, 6),
            unit="p-value",
            threshold=policy.ks_p_value_threshold,
            breached=ks_breached,
            comparison_period=(
                f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL} "
                f"(KS statistic {round(statistic, 3)})"
            ),
        ),
    ]
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=DriftDomain.COMPETITOR_INDEX.value,
        domain=DriftDomain.COMPETITOR_INDEX,
        measurements=measurements,
        breached=breached,
        investigation_required=breached,
        confidence_impact=0.3 if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=f"Competitor price index moved {round(movement, 1)}%; KS p-value {round(p_value, 4)}.",
    )


def _feedback_topics_alert(settings: Settings) -> DriftAlert:
    series = generate_feedback_topic_series()
    baseline = series[BASELINE_START_INDEX:BASELINE_END_INDEX]
    current = series[DRIFT_CURRENT_INDEX]
    policy = settings.drift
    if len(baseline) < policy.minimum_baseline_months:
        return _insufficient_sample_alert(DriftDomain.FEEDBACK_TOPICS, settings)

    baseline_shares = [
        sum(r.claims_handling_share_pct for r in baseline) / len(baseline) / 100,
        sum(r.price_share_pct for r in baseline) / len(baseline) / 100,
        sum(r.communication_share_pct for r in baseline) / len(baseline) / 100,
        sum(r.other_share_pct for r in baseline) / len(baseline) / 100,
    ]
    current_shares = [
        current.claims_handling_share_pct / 100,
        current.price_share_pct / 100,
        current.communication_share_pct / 100,
        current.other_share_pct / 100,
    ]
    psi = population_stability_index(baseline_shares, current_shares)
    baseline_price = sum(r.price_share_pct for r in baseline) / len(baseline)
    movement = percentage_movement(baseline_price, current.price_share_pct)
    psi_breached = psi > policy.psi_threshold
    movement_breached = abs(movement) > policy.percentage_movement_threshold_pct
    breached = psi_breached or movement_breached
    measurements = [
        DriftMeasurement(
            measure_kind=DriftMeasureKind.POPULATION_STABILITY_INDEX,
            value=round(psi, 4),
            unit="PSI",
            threshold=policy.psi_threshold,
            breached=psi_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL} average topic mix",
        ),
        DriftMeasurement(
            measure_kind=DriftMeasureKind.PERCENTAGE_MOVEMENT,
            value=round(movement, 2),
            unit="%",
            threshold=policy.percentage_movement_threshold_pct,
            breached=movement_breached,
            comparison_period=(
                f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL} (price-related share)"
            ),
        ),
    ]
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=DriftDomain.FEEDBACK_TOPICS.value,
        domain=DriftDomain.FEEDBACK_TOPICS,
        measurements=measurements,
        breached=breached,
        investigation_required=breached,
        confidence_impact=0.3 if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=(
            f"Feedback topic mix PSI is {round(psi, 3)}; price-related share moved "
            f"{round(movement, 1)}%."
        ),
    )


def detect_data_drift(settings: Settings) -> list[DriftAlert]:
    database = PersistentAnalyticsDatabase(settings.analytics_database_path)
    severities, frequencies, loss_ratios = _claims_metrics(database)
    conversions = _conversion_metric(database)

    def baseline_and_current(series: list[float]) -> tuple[list[float], float]:
        return series[BASELINE_START_INDEX:BASELINE_END_INDEX], series[DRIFT_CURRENT_INDEX]

    severity_baseline, severity_current = baseline_and_current(severities)
    frequency_baseline, frequency_current = baseline_and_current(frequencies)
    loss_ratio_baseline, loss_ratio_current = baseline_and_current(loss_ratios)
    conversion_baseline, conversion_current = baseline_and_current(conversions)

    return [
        _z_and_movement_alert(
            domain=DriftDomain.CLAIM_SEVERITY,
            baseline=severity_baseline,
            current_value=severity_current,
            unit="GBP per claim",
            settings=settings,
        ),
        _z_and_movement_alert(
            domain=DriftDomain.CLAIM_FREQUENCY,
            baseline=frequency_baseline,
            current_value=frequency_current,
            unit="claims per policy",
            settings=settings,
        ),
        _z_and_movement_alert(
            domain=DriftDomain.LOSS_RATIO,
            baseline=loss_ratio_baseline,
            current_value=loss_ratio_current,
            unit="incurred loss / earned premium",
            settings=settings,
        ),
        _z_and_movement_alert(
            domain=DriftDomain.CONVERSION,
            baseline=conversion_baseline,
            current_value=conversion_current,
            unit="sales / quotes",
            settings=settings,
        ),
        _competitor_alert(database, settings),
        _feedback_topics_alert(settings),
    ]
