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
from pricing_copilot.evaluation.gate import evaluate_promotion_gate
from pricing_copilot.evaluation.store import load_promoted_report, save_promoted_report
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


def _report(
    actuals: EvaluationActuals, case_results: list[CaseResult] | None = None
) -> BenchmarkReport:
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


def test_promotion_gate_promotes_a_fully_passing_report() -> None:
    result = evaluate_promotion_gate(_report(_actuals()))
    assert result.promoted is True
    assert result.failing_metrics == []
    assert result.failing_case_ids == []


def test_promotion_gate_rejects_a_report_below_a_floor_target() -> None:
    result = evaluate_promotion_gate(_report(_actuals(specialist_routing_accuracy_pct=50.0)))
    assert result.promoted is False
    assert any("specialist_routing_accuracy_pct" in metric for metric in result.failing_metrics)


def test_promotion_gate_rejects_a_report_above_a_ceiling_target() -> None:
    result = evaluate_promotion_gate(_report(_actuals(latency_p95_seconds=999.0)))
    assert result.promoted is False
    assert any("latency_p95_seconds" in metric for metric in result.failing_metrics)


def test_promotion_gate_records_failing_case_ids() -> None:
    failing_case = CaseResult(
        case_id="GC-99",
        category=CaseCategory.NORMAL,
        architecture="governed",
        outcome=CaseOutcome.FAILED,
        duration_ms=1.0,
    )
    result = evaluate_promotion_gate(_report(_actuals(), [failing_case]))
    assert result.promoted is False
    assert result.failing_case_ids == ["GC-99"]


def test_promoted_report_round_trips_through_disk(tmp_path: Path) -> None:
    settings = Settings(evaluation_directory=tmp_path / "evaluation")
    assert load_promoted_report(settings) is None
    save_promoted_report(_report(_actuals()), settings)
    loaded = load_promoted_report(settings)
    assert loaded is not None
    assert loaded.report_version == "benchmark-report-v1"
