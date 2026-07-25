from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.drift.operational_detector import detect_operational_drift
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.versions import current_configuration_versions


def _actuals(**overrides: object) -> EvaluationActuals:
    base = EvaluationActuals(
        deterministic_accuracy_pct=100.0,
        output_schema_valid_pct=100.0,
        citation_coverage_pct=100.0,
        ambiguous_abstention_pct=100.0,
        prompt_injection_success_pct=0.0,
        critical_guardrail_pass_pct=100.0,
        specialist_routing_accuracy_pct=100.0,
        unsupported_recommendation_count=0,
        latency_p95_seconds=10.0,
        tool_call_failure_pct=0.0,
        total_estimated_cost_gbp=0.0,
        total_tokens=0,
        governance_rejection_count=0,
        safe_abstention_count=0,
        cases_passed=10,
        cases_failed=0,
        cases_errored=0,
    )
    return base.model_copy(update=overrides)


def _report(actuals: EvaluationActuals) -> BenchmarkReport:
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=[],
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(Settings()),
        governed=governed,
    )


def test_detect_operational_drift_flags_high_latency() -> None:
    report = _report(_actuals(latency_p95_seconds=60.0))
    alerts = detect_operational_drift(report, Settings())
    latency_alert = next(a for a in alerts if a.metric_name == "latency_p95_seconds")
    assert latency_alert.category is DriftAlertCategory.OPERATIONAL
    assert latency_alert.breached is True


def test_detect_operational_drift_passes_when_within_ceilings() -> None:
    report = _report(_actuals())
    alerts = detect_operational_drift(report, Settings())
    assert all(not a.breached for a in alerts if a.metric_name != "token_and_cost_usage")
