from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory
from pricing_copilot.evaluation.contracts import BenchmarkReport

BASELINE_WINDOW_LABEL = "operational policy ceiling"
CURRENT_WINDOW_LABEL = "latest governed benchmark run"


def detect_operational_drift(report: BenchmarkReport, settings: Settings) -> list[DriftAlert]:
    actuals = report.governed.actuals
    policy = settings.drift

    latency_breached = actuals.latency_p95_seconds > policy.latency_p95_ceiling_seconds
    tool_failure_breached = actuals.tool_call_failure_pct > policy.tool_failure_ceiling_pct
    invalid_output_breached = actuals.output_schema_valid_pct < 100.0

    return [
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="latency_p95_seconds",
            breached=latency_breached,
            investigation_required=latency_breached,
            confidence_impact=0.2 if latency_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"P95 latency is {actuals.latency_p95_seconds}s, "
                f"ceiling is {policy.latency_p95_ceiling_seconds}s."
            ),
        ),
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="tool_call_failure_pct",
            breached=tool_failure_breached,
            investigation_required=tool_failure_breached,
            confidence_impact=0.2 if tool_failure_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Tool call failure rate is {actuals.tool_call_failure_pct}%, "
                f"ceiling is {policy.tool_failure_ceiling_pct}%."
            ),
        ),
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="output_schema_valid_pct",
            breached=invalid_output_breached,
            investigation_required=invalid_output_breached,
            confidence_impact=0.3 if invalid_output_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Output schema validity is {actuals.output_schema_valid_pct}%, target is 100%.",
        ),
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="token_and_cost_usage",
            breached=False,
            investigation_required=False,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Total tokens: {actuals.total_tokens}, "
                f"estimated cost: GBP {actuals.total_estimated_cost_gbp}."
            ),
        ),
    ]
