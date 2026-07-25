import asyncio

from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.evidence.models import EvidenceLedger
from pricing_copilot.orchestration.governance_agent import FakeGovernanceAgentRunner
from pricing_copilot.recommendation.contracts import RecommendationDraft


def _draft() -> RecommendationDraft:
    return RecommendationDraft(action=RecommendationAction.HOLD, rationale="Hold for now.")


def test_fake_governance_agent_defaults_to_approving() -> None:
    runner = FakeGovernanceAgentRunner()
    review = asyncio.run(
        runner.review(draft=_draft(), specialist_reports=[], ledger=EvidenceLedger())
    )
    assert review.approved is True


def test_fake_governance_agent_can_be_configured_to_reject_then_approve() -> None:
    runner = FakeGovernanceAgentRunner(approvals=[False, True])
    first = asyncio.run(
        runner.review(draft=_draft(), specialist_reports=[], ledger=EvidenceLedger())
    )
    second = asyncio.run(
        runner.review(draft=_draft(), specialist_reports=[], ledger=EvidenceLedger())
    )
    assert first.approved is False
    assert first.feedback
    assert second.approved is True


def test_fake_governance_agent_repeats_final_configured_value_on_further_calls() -> None:
    runner = FakeGovernanceAgentRunner(approvals=[False])
    asyncio.run(runner.review(draft=_draft(), specialist_reports=[], ledger=EvidenceLedger()))
    third = asyncio.run(
        runner.review(draft=_draft(), specialist_reports=[], ledger=EvidenceLedger())
    )
    assert third.approved is False
