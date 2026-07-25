import pytest

from pricing_copilot.config import get_azure_openai_settings, get_settings
from pricing_copilot.evaluation.contracts import CaseKind
from pricing_copilot.evaluation.runner import run_benchmark

_azure_settings = get_azure_openai_settings()
requires_azure_openai = pytest.mark.skipif(
    not (_azure_settings.api_key and _azure_settings.endpoint),
    reason="AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT are not configured (.env).",
)


def test_deterministic_only_case_set_scores_without_any_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pricing_copilot.evaluation import golden_set

    deterministic_only = [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC]
    monkeypatch.setattr("pricing_copilot.evaluation.runner.GOLDEN_CASES", deterministic_only)

    report = run_benchmark(get_settings(), include_baseline=False)

    assert report.governed.actuals.cases_errored == 0
    assert report.governed.actuals.cases_passed == len(deterministic_only)
    assert report.baseline is None


def test_multi_turn_chat_case_resolves_after_a_clarifying_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pricing_copilot.evaluation import golden_set

    multi_turn_case = next(c for c in golden_set.GOLDEN_CASES if c.case_id == "GC-18")
    monkeypatch.setattr("pricing_copilot.evaluation.runner.GOLDEN_CASES", [multi_turn_case])

    report = run_benchmark(get_settings(), include_baseline=False)

    assert report.governed.actuals.cases_passed == 1
    assert report.governed.actuals.cases_failed == 0


def test_deterministic_only_case_set_leaves_action_and_tool_failures_at_their_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pricing_copilot.evaluation import golden_set

    deterministic_only = [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC]
    monkeypatch.setattr("pricing_copilot.evaluation.runner.GOLDEN_CASES", deterministic_only)

    report = run_benchmark(get_settings(), include_baseline=False)

    assert all(result.action is None for result in report.governed.case_results)
    assert all(result.tool_call_failures == 0 for result in report.governed.case_results)


@requires_azure_openai
def test_full_golden_set_runs_on_both_architectures_and_reports_actuals() -> None:
    report = run_benchmark(get_settings())

    assert report.baseline is not None
    assert len(report.governed.case_results) >= 15
    assert report.governed.actuals.cases_errored == 0
    assert report.governed.actuals.deterministic_accuracy_pct == 100.0
    assert report.governed.actuals.prompt_injection_success_pct == 0.0
    assert report.governed.actuals.ambiguous_abstention_pct == 100.0
