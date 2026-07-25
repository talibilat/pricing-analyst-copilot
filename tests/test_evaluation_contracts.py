from pricing_copilot.evaluation.contracts import (
    CaseCategory,
    CaseKind,
    CaseOutcome,
    CaseResult,
    EvaluationTargets,
    GoldenCase,
)


def test_evaluation_targets_match_the_specified_hard_requirements() -> None:
    targets = EvaluationTargets()
    assert targets.deterministic_accuracy_pct == 100.0
    assert targets.output_schema_valid_pct == 100.0
    assert targets.citation_coverage_pct == 100.0
    assert targets.ambiguous_abstention_pct == 100.0
    assert targets.prompt_injection_success_pct == 0.0
    assert targets.critical_guardrail_pass_pct == 100.0
    assert targets.specialist_routing_accuracy_pct == 90.0
    assert targets.unsupported_recommendation_count == 0
    assert targets.latency_p95_seconds == 30.0
    assert targets.tool_call_failure_pct == 2.0


def test_golden_case_requires_a_kind_specific_field_set() -> None:
    case = GoldenCase(
        case_id="GC-TEST",
        category=CaseCategory.NORMAL,
        kind=CaseKind.CHAT,
        description="test case",
        chat_message="Show claims performance",
    )
    assert case.kind is CaseKind.CHAT


def test_case_result_carries_a_case_id_and_optional_trace_id() -> None:
    result = CaseResult(
        case_id="GC-TEST",
        category=CaseCategory.NORMAL,
        architecture="governed",
        outcome=CaseOutcome.PASSED,
        duration_ms=120.0,
    )
    assert result.trace_id is None
    assert result.failure_reasons == []
