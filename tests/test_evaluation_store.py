from datetime import UTC, datetime
from pathlib import Path

from pricing_copilot.config import Settings
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    CaseCategory,
    CaseOutcome,
    CaseResult,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.evaluation.store import load_benchmark_report, save_benchmark_report
from pricing_copilot.versions import current_configuration_versions


def _report(settings: Settings) -> BenchmarkReport:
    actuals = EvaluationActuals(
        deterministic_accuracy_pct=100.0,
        output_schema_valid_pct=100.0,
        citation_coverage_pct=100.0,
        ambiguous_abstention_pct=100.0,
        prompt_injection_success_pct=0.0,
        critical_guardrail_pass_pct=100.0,
        specialist_routing_accuracy_pct=95.0,
        unsupported_recommendation_count=0,
        latency_p95_seconds=2.0,
        tool_call_failure_pct=0.0,
        total_estimated_cost_gbp=0.0,
        total_tokens=0,
        governance_rejection_count=0,
        safe_abstention_count=1,
        cases_passed=1,
        cases_failed=0,
        cases_errored=0,
    )
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=[
            CaseResult(
                case_id="GC-01",
                category=CaseCategory.NORMAL,
                architecture="governed",
                outcome=CaseOutcome.PASSED,
                duration_ms=10.0,
            )
        ],
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(settings),
        governed=governed,
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    settings = Settings(evaluation_directory=tmp_path / "evaluation")
    save_benchmark_report(_report(settings), settings)

    loaded = load_benchmark_report(settings)
    assert loaded is not None
    assert loaded.governed.actuals.cases_passed == 1


def test_load_returns_none_when_nothing_is_recorded(tmp_path: Path) -> None:
    settings = Settings(evaluation_directory=tmp_path / "evaluation")
    assert load_benchmark_report(settings) is None
