from pricing_copilot.orchestration.contracts import GovernanceReview, SpecialistFindings


def test_specialist_findings_defaults_to_no_cited_ids() -> None:
    findings = SpecialistFindings(summary="Loss ratio rose.")
    assert findings.cited_evidence_ids == []


def test_governance_review_defaults_to_empty_feedback() -> None:
    review = GovernanceReview(approved=True)
    assert review.feedback == ""
