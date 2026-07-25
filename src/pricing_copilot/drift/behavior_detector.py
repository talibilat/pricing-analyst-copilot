from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory
from pricing_copilot.evaluation.contracts import BenchmarkReport

BASELINE_WINDOW_LABEL = "golden-suite target"
CURRENT_WINDOW_LABEL = "latest governed benchmark run"


def _floor_alert(metric_name: str, actual: float, floor: float, impact: float) -> DriftAlert:
    breached = actual < floor
    return DriftAlert(
        category=DriftAlertCategory.BEHAVIOR,
        metric_name=metric_name,
        breached=breached,
        investigation_required=breached,
        confidence_impact=impact if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=f"{metric_name} is {actual}%, floor is {floor}%.",
    )


def detect_behavior_drift(report: BenchmarkReport, settings: Settings) -> list[DriftAlert]:
    actuals = report.governed.actuals
    policy = settings.drift
    alerts = [
        _floor_alert(
            "specialist_routing_accuracy_pct",
            actuals.specialist_routing_accuracy_pct,
            policy.routing_accuracy_floor_pct,
            0.3,
        ),
        _floor_alert(
            "citation_coverage_pct",
            actuals.citation_coverage_pct,
            policy.citation_coverage_floor_pct,
            0.3,
        ),
        _floor_alert(
            "ambiguous_abstention_pct",
            actuals.ambiguous_abstention_pct,
            policy.safe_abstention_floor_pct,
            0.3,
        ),
    ]

    rejection_breached = (
        actuals.governance_rejection_count > policy.governance_rejection_ceiling_count
    )
    alerts.append(
        DriftAlert(
            category=DriftAlertCategory.BEHAVIOR,
            metric_name="governance_rejection_count",
            breached=rejection_breached,
            investigation_required=rejection_breached,
            confidence_impact=0.2 if rejection_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Governance rejections: {actuals.governance_rejection_count}, "
                f"ceiling is {policy.governance_rejection_ceiling_count}."
            ),
        )
    )

    total_cases = actuals.cases_passed + actuals.cases_failed + actuals.cases_errored
    pass_rate = (100.0 * actuals.cases_passed / total_cases) if total_cases else 0.0
    suite_breached = pass_rate < policy.golden_suite_pass_floor_pct
    alerts.append(
        DriftAlert(
            category=DriftAlertCategory.BEHAVIOR,
            metric_name="golden_suite_pass_rate_pct",
            breached=suite_breached,
            investigation_required=suite_breached,
            confidence_impact=0.4 if suite_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Golden-suite pass rate is {round(pass_rate, 2)}%, "
                f"floor is {policy.golden_suite_pass_floor_pct}%."
            ),
        )
    )

    distribution: dict[str, int] = {}
    for result in report.governed.case_results:
        if result.action is not None:
            distribution[result.action.value] = distribution.get(result.action.value, 0) + 1
    alerts.append(
        DriftAlert(
            category=DriftAlertCategory.BEHAVIOR,
            metric_name="recommendation_distribution",
            breached=False,
            investigation_required=False,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Recommendation action distribution across governed cases: {distribution}.",
        )
    )
    return alerts
