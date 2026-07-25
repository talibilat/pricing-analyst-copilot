from pricing_copilot.evaluation.scoring import DETERMINISTIC_CHECKS


def test_movement_clamp_check_passes() -> None:
    passed, detail = DETERMINISTIC_CHECKS["movement_clamp"]()
    assert passed, detail


def test_zero_claims_rejected_check_passes() -> None:
    passed, detail = DETERMINISTIC_CHECKS["zero_claims_rejected"]()
    assert passed, detail


def test_stale_document_flagged_check_passes() -> None:
    passed, detail = DETERMINISTIC_CHECKS["stale_document_flagged"]()
    assert passed, detail


def test_all_golden_set_check_ids_are_registered() -> None:
    from pricing_copilot.evaluation.contracts import CaseKind
    from pricing_copilot.evaluation.golden_set import GOLDEN_CASES

    for case in GOLDEN_CASES:
        if case.kind is CaseKind.DETERMINISTIC:
            assert case.check_id in DETERMINISTIC_CHECKS, case.check_id
