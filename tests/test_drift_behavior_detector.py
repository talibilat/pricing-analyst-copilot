from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.drift.behavior_detector import detect_behavior_drift
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    CaseCategory,
    CaseOutcome,
    CaseResult,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.versions import current_configuration_versions


def _actuals(**overrides: object) -> EvaluationActuals:
    base = dict(
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
    base.update(overrides)
    return EvaluationActuals(**base)


def _report(actuals: EvaluationActuals, case_results: list[CaseResult] | None = None) -> BenchmarkReport:
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=case_results or [],
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(Settings()),
        governed=governed,
    )


def test_detect_behavior_drift_flags_low_routing_accuracy() -> None:
    report = _report(_actuals(specialist_routing_accuracy_pct=50.0))
    alerts = detect_behavior_drift(report, Settings())
    routing_alert = next(a for a in alerts if a.metric_name == "specialist_routing_accuracy_pct")
    assert routing_alert.category is DriftAlertCategory.BEHAVIOR
    assert routing_alert.breached is True


def test_detect_behavior_drift_reports_recommendation_distribution() -> None:
    case_results = [
        CaseResult(
            case_id="GC-1",
            category=CaseCategory.NORMAL,
            architecture="governed",
            outcome=CaseOutcome.PASSED,
            duration_ms=1.0,
            action=RecommendationAction.INCREASE,
        ),
        CaseResult(
            case_id="GC-2",
            category=CaseCategory.NORMAL,
            architecture="governed",
            outcome=CaseOutcome.PASSED,
            duration_ms=1.0,
            action=RecommendationAction.HOLD,
        ),
    ]
    report = _report(_actuals(), case_results)
    alerts = detect_behavior_drift(report, Settings())
    distribution_alert = next(a for a in alerts if a.metric_name == "recommendation_distribution")
    assert "increase" in distribution_alert.detail
    assert "hold" in distribution_alert.detail
