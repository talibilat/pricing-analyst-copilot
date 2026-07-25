from pricing_copilot.evaluation.contracts import CaseCategory
from pricing_copilot.evaluation.golden_set import GOLDEN_CASES, GOLDEN_SET_VERSION


def test_golden_set_has_at_least_fifteen_cases() -> None:
    assert len(GOLDEN_CASES) >= 15


def test_golden_set_case_ids_are_unique() -> None:
    ids = [case.case_id for case in GOLDEN_CASES]
    assert len(ids) == len(set(ids))


def test_golden_set_meets_the_minimum_category_coverage() -> None:
    counts: dict[CaseCategory, int] = {}
    for case in GOLDEN_CASES:
        counts[case.category] = counts.get(case.category, 0) + 1
    assert counts.get(CaseCategory.NORMAL, 0) >= 5
    assert counts.get(CaseCategory.AMBIGUOUS, 0) >= 3
    assert counts.get(CaseCategory.MISSING_DATA, 0) >= 2
    assert counts.get(CaseCategory.PROMPT_INJECTION, 0) >= 2
    assert counts.get(CaseCategory.EXTREME_VALUE, 0) >= 2
    assert counts.get(CaseCategory.STALE_DATA, 0) >= 1


def test_golden_set_version_is_set() -> None:
    assert GOLDEN_SET_VERSION


def test_every_case_declares_scoring_relevant_fields_for_its_kind() -> None:
    from pricing_copilot.evaluation.contracts import CaseKind

    for case in GOLDEN_CASES:
        if case.kind is CaseKind.CHAT:
            assert case.chat_message
        elif case.kind is CaseKind.PRICING_WORKFLOW:
            assert case.question is not None
        elif case.kind is CaseKind.DETERMINISTIC:
            assert case.check_id
