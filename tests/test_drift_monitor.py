from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.drift.monitor import run_drift_monitoring
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.versions import current_configuration_versions


def _benchmark_report(settings: Settings) -> BenchmarkReport:
    actuals = EvaluationActuals(
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
        configuration_versions=current_configuration_versions(settings),
        governed=governed,
    )


def test_run_drift_monitoring_produces_alerts_across_all_four_categories(tmp_path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    report = run_drift_monitoring(settings, _benchmark_report(settings))
    categories = {alert.category for alert in report.alerts}
    assert categories == set(DriftAlertCategory)


def test_run_drift_monitoring_saves_the_current_configuration_for_next_time(tmp_path) -> None:
    from pricing_copilot.drift.store import load_previous_configuration

    settings = Settings(drift_directory=tmp_path / "drift")
    assert load_previous_configuration(settings) is None
    run_drift_monitoring(settings, _benchmark_report(settings))
    assert load_previous_configuration(settings) is not None
