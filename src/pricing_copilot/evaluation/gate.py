from __future__ import annotations

from pydantic import BaseModel, Field

from pricing_copilot.evaluation.contracts import BenchmarkReport, CaseOutcome

_FLOOR_METRICS = (
    "deterministic_accuracy_pct",
    "output_schema_valid_pct",
    "citation_coverage_pct",
    "ambiguous_abstention_pct",
    "critical_guardrail_pass_pct",
    "specialist_routing_accuracy_pct",
)
_CEILING_METRICS = (
    "prompt_injection_success_pct",
    "unsupported_recommendation_count",
    "latency_p95_seconds",
    "tool_call_failure_pct",
)


class PromotionGateResult(BaseModel):
    promoted: bool
    failing_metrics: list[str] = Field(default_factory=list)
    failing_case_ids: list[str] = Field(default_factory=list)
    detail: str


def evaluate_promotion_gate(report: BenchmarkReport) -> PromotionGateResult:
    actuals = report.governed.actuals
    targets = report.governed.targets
    failing_metrics: list[str] = []
    for metric in _FLOOR_METRICS:
        actual_value = getattr(actuals, metric)
        target_value = getattr(targets, metric)
        if actual_value < target_value:
            failing_metrics.append(f"{metric}: actual {actual_value} below target {target_value}")
    for metric in _CEILING_METRICS:
        actual_value = getattr(actuals, metric)
        target_value = getattr(targets, metric)
        if actual_value > target_value:
            failing_metrics.append(f"{metric}: actual {actual_value} above target {target_value}")

    failing_case_ids = [
        result.case_id
        for result in report.governed.case_results
        if result.outcome != CaseOutcome.PASSED
    ]
    promoted = not failing_metrics and not failing_case_ids
    detail = (
        "All evaluation gates passed; this report is promoted as the current default."
        if promoted
        else (
            f"{len(failing_metrics)} metric(s) and {len(failing_case_ids)} case(s) failed; "
            "the current default configuration is preserved."
        )
    )
    return PromotionGateResult(
        promoted=promoted,
        failing_metrics=failing_metrics,
        failing_case_ids=failing_case_ids,
        detail=detail,
    )
