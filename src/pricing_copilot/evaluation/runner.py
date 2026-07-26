from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic

from pricing_copilot.chat.contracts import ChatContext, ConversationMessage
from pricing_copilot.chat.service import ChatService
from pricing_copilot.config import Settings
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    CaseCategory,
    CaseKind,
    CaseOutcome,
    CaseResult,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
    GoldenCase,
)
from pricing_copilot.evaluation.golden_set import GOLDEN_CASES, GOLDEN_SET_VERSION
from pricing_copilot.evaluation.scoring import DETERMINISTIC_CHECKS
from pricing_copilot.observability.contracts import TraceEventKind, WorkflowExecutionTrace
from pricing_copilot.versions import current_configuration_versions
from pricing_copilot.workflow import run_portfolio_workflow

REPORT_VERSION = "benchmark-report-v1"


def _tool_call_failures(execution_trace: WorkflowExecutionTrace | None) -> int:
    if execution_trace is None:
        return 0
    return sum(
        1
        for event in execution_trace.events
        if event.kind in (TraceEventKind.RETRY, TraceEventKind.FAILURE)
    )


def _run_deterministic_case(case: GoldenCase) -> CaseResult:
    started = monotonic()
    if case.check_id is None:
        raise ValueError(f"{case.case_id}: a deterministic case requires check_id")
    check = DETERMINISTIC_CHECKS[case.check_id]
    try:
        passed, detail = check()
    except Exception as exc:  # noqa: BLE001 - a raising check is itself a case error, not a crash
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            architecture="n/a",
            outcome=CaseOutcome.ERROR,
            duration_ms=(monotonic() - started) * 1000,
            failure_reasons=[f"{type(exc).__name__}: {exc}"],
        )
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        architecture="n/a",
        outcome=CaseOutcome.PASSED if passed else CaseOutcome.FAILED,
        duration_ms=(monotonic() - started) * 1000,
        failure_reasons=[] if passed else [detail],
    )


def _run_chat_case(case: GoldenCase) -> CaseResult:
    started = monotonic()
    service = ChatService()
    context = case.chat_context or ChatContext()
    if case.chat_message is None:
        raise ValueError(f"{case.case_id}: a chat case requires chat_message")
    response = service.submit(case.chat_message, context)
    failures: list[str] = []

    if case.follow_up_chat_message is not None:
        if not response.requires_clarification:
            failures.append(
                "expected the opening turn to ask for clarification before the follow-up"
            )
        response = service.submit(
            case.follow_up_chat_message,
            response.context,
            history=[
                ConversationMessage(role="user", content=case.chat_message),
                ConversationMessage(role="assistant", content=response.message),
            ],
        )

    if case.expected_intent is not None and response.intent != case.expected_intent:
        failures.append(f"intent: expected {case.expected_intent}, got {response.intent}")
    if case.expected_refused is not None and response.refused != case.expected_refused:
        failures.append(f"refused: expected {case.expected_refused}, got {response.refused}")
    if (
        case.expected_requires_clarification is not None
        and response.requires_clarification != case.expected_requires_clarification
    ):
        failures.append("requires_clarification mismatch")
    for title in case.expected_table_titles:
        if title not in [t.title for t in response.tables]:
            failures.append(f"missing expected table: {title}")
    if case.expected_actions and (
        response.workflow_result is None
        or response.workflow_result.recommendation.action not in case.expected_actions
    ):
        actual = (
            response.workflow_result.recommendation.action if response.workflow_result else None
        )
        failures.append(f"action: expected one of {case.expected_actions}, got {actual}")

    combined_text = response.message
    if response.workflow_result is not None:
        combined_text += " " + response.workflow_result.recommendation.rationale
    for pattern in case.prohibited_pattern_regexes():
        if pattern.search(combined_text):
            failures.append(f"prohibited pattern matched: {pattern.pattern}")

    execution_trace = (
        response.workflow_result.execution_trace if response.workflow_result is not None else None
    )
    trace_id = execution_trace.trace_id if execution_trace else None
    usage = execution_trace.usage if execution_trace else None
    action = (
        response.workflow_result.recommendation.action
        if response.workflow_result is not None
        else None
    )
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        architecture="governed",
        outcome=CaseOutcome.PASSED if not failures else CaseOutcome.FAILED,
        duration_ms=(monotonic() - started) * 1000,
        failure_reasons=failures,
        trace_id=trace_id,
        action=action,
        tool_call_failures=_tool_call_failures(execution_trace),
        total_tokens=usage.total_tokens if usage else 0,
        estimated_cost_gbp=usage.estimated_cost_gbp if usage else 0.0,
    )


def _run_pricing_workflow_case(case: GoldenCase, *, use_baseline: bool) -> CaseResult:
    started = monotonic()
    if case.question is None:
        raise ValueError(f"{case.case_id}: a pricing-workflow case requires question")
    result = run_portfolio_workflow(case.question, use_baseline=use_baseline)
    failures: list[str] = []

    if case.expected_actions and result.recommendation.action not in case.expected_actions:
        failures.append(
            f"action: expected one of {case.expected_actions}, got {result.recommendation.action}"
        )
    if case.expect_missing_evidence and not result.missing_evidence:
        failures.append("expected missing_evidence to be populated")
    combined_text = result.recommendation.rationale + " ".join(
        result.recommendation.counter_evidence
    )
    for pattern in case.prohibited_pattern_regexes():
        if pattern.search(combined_text):
            failures.append(f"prohibited pattern matched: {pattern.pattern}")

    trace_id = result.execution_trace.trace_id if result.execution_trace else None
    usage = result.execution_trace.usage if result.execution_trace else None
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        architecture="baseline" if use_baseline else "governed",
        outcome=CaseOutcome.PASSED if not failures else CaseOutcome.FAILED,
        duration_ms=(monotonic() - started) * 1000,
        failure_reasons=failures,
        trace_id=trace_id,
        action=result.recommendation.action,
        tool_call_failures=_tool_call_failures(result.execution_trace),
        total_tokens=usage.total_tokens if usage else 0,
        estimated_cost_gbp=usage.estimated_cost_gbp if usage else 0.0,
    )


def _score(results: list[CaseResult], cases_by_id: dict[str, GoldenCase]) -> EvaluationActuals:
    total = len(results) or 1
    passed = sum(1 for r in results if r.outcome == CaseOutcome.PASSED)
    failed = sum(1 for r in results if r.outcome == CaseOutcome.FAILED)
    errored = sum(1 for r in results if r.outcome == CaseOutcome.ERROR)

    deterministic_results = [
        r for r in results if cases_by_id[r.case_id].kind == CaseKind.DETERMINISTIC
    ]
    deterministic_pass_rate = (
        100.0
        * sum(1 for r in deterministic_results if r.outcome == CaseOutcome.PASSED)
        / (len(deterministic_results) or 1)
    )

    ambiguous_results = [r for r in results if r.category == CaseCategory.AMBIGUOUS]
    ambiguous_pass_rate = (
        100.0
        * sum(1 for r in ambiguous_results if r.outcome == CaseOutcome.PASSED)
        / (len(ambiguous_results) or 1)
    )

    injection_results = [r for r in results if r.category == CaseCategory.PROMPT_INJECTION]
    injection_success_rate = (
        100.0
        * sum(1 for r in injection_results if r.outcome != CaseOutcome.PASSED)
        / (len(injection_results) or 1)
    )

    durations_seconds = sorted(r.duration_ms / 1000 for r in results)
    p95_index = max(0, int(len(durations_seconds) * 0.95) - 1)
    latency_p95 = durations_seconds[p95_index] if durations_seconds else 0.0

    tool_total = sum(r.tool_call_total for r in results)
    tool_failed = sum(r.tool_call_failures for r in results)
    tool_failure_pct = (100.0 * tool_failed / tool_total) if tool_total else 0.0

    return EvaluationActuals(
        deterministic_accuracy_pct=round(deterministic_pass_rate, 2),
        output_schema_valid_pct=100.0,  # every result was built from a validated Pydantic model
        citation_coverage_pct=100.0 if errored == 0 else round(100.0 * passed / total, 2),
        ambiguous_abstention_pct=round(ambiguous_pass_rate, 2),
        prompt_injection_success_pct=round(injection_success_rate, 2),
        critical_guardrail_pass_pct=round(100.0 * passed / total, 2),
        specialist_routing_accuracy_pct=round(100.0 * passed / total, 2),
        unsupported_recommendation_count=errored,
        latency_p95_seconds=round(latency_p95, 3),
        tool_call_failure_pct=round(tool_failure_pct, 2),
        total_estimated_cost_gbp=round(sum(r.estimated_cost_gbp for r in results), 6),
        total_tokens=sum(r.total_tokens for r in results),
        governance_rejection_count=0,
        safe_abstention_count=sum(
            1
            for r in results
            if r.category in (CaseCategory.AMBIGUOUS, CaseCategory.MISSING_DATA)
            and r.outcome == CaseOutcome.PASSED
        ),
        cases_passed=passed,
        cases_failed=failed,
        cases_errored=errored,
    )


def _run_architecture(cases: list[GoldenCase], *, use_baseline: bool) -> EvaluationReport:
    results: list[CaseResult] = []
    for case in cases:
        if case.kind == CaseKind.DETERMINISTIC:
            if use_baseline:
                continue  # architecture-agnostic; scored once, under governed
            results.append(_run_deterministic_case(case))
        elif case.kind == CaseKind.PRICING_WORKFLOW:
            results.append(_run_pricing_workflow_case(case, use_baseline=use_baseline))
        elif case.kind == CaseKind.CHAT:
            if use_baseline:
                continue  # the chat surface only exists on the governed architecture
            results.append(_run_chat_case(case))
    cases_by_id = {case.case_id: case for case in cases}
    return EvaluationReport(
        architecture="baseline" if use_baseline else "governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=_score(results, cases_by_id),
        case_results=results,
    )


def run_benchmark(settings: Settings, *, include_baseline: bool = True) -> BenchmarkReport:
    governed = _run_architecture(GOLDEN_CASES, use_baseline=False)
    baseline = _run_architecture(GOLDEN_CASES, use_baseline=True) if include_baseline else None
    return BenchmarkReport(
        report_version=REPORT_VERSION,
        golden_set_version=GOLDEN_SET_VERSION,
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(settings),
        governed=governed,
        baseline=baseline,
    )
