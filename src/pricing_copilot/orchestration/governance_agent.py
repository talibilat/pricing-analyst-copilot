from __future__ import annotations

import json
from typing import Protocol

from agents import Agent, OpenAIChatCompletionsModel

from pricing_copilot.contracts import SpecialistReport
from pricing_copilot.evidence.models import EvidenceLedger
from pricing_copilot.orchestration.contracts import GovernanceReview
from pricing_copilot.orchestration.runtime import AgentRuntime
from pricing_copilot.recommendation.contracts import RecommendationDraft

GOVERNANCE_AGENT_SYSTEM_PROMPT = (
    "You are the independent governance agent in a governed insurance pricing decision-support "
    "prototype. You did NOT write the draft recommendation you are reviewing, and you do not "
    "have database or document access - you review the draft strictly against the specialist "
    "reports and evidence ledger entries provided to you. Reject (approved=false) if: the action "
    "contradicts what the specialist reports actually say; material evidence that opposes the "
    "proposed action is missing from the draft's counter_evidence; or the rationale implies a "
    "price has already been executed rather than merely proposed. Otherwise approve. When you "
    "reject, feedback must name the specific problem so it can be fixed in one revision. "
    'Respond with a single JSON object: {"approved": boolean, "feedback": string}.'
)


class GovernanceAgentRunner(Protocol):
    async def review(
        self,
        *,
        draft: RecommendationDraft,
        specialist_reports: list[SpecialistReport],
        ledger: EvidenceLedger,
    ) -> GovernanceReview: ...


class FakeGovernanceAgentRunner:
    """Deterministic stand-in for tests and offline runs - makes no network calls. `approvals`
    is consumed in order across successive calls; the last entry repeats once exhausted, so a
    single-element list like [False] models "always rejects" for bounded-revision tests."""

    def __init__(self, approvals: list[bool] | None = None) -> None:
        self._approvals = approvals if approvals is not None else [True]
        self._call_count = 0

    async def review(
        self,
        *,
        draft: RecommendationDraft,
        specialist_reports: list[SpecialistReport],
        ledger: EvidenceLedger,
    ) -> GovernanceReview:
        index = min(self._call_count, len(self._approvals) - 1)
        approved = self._approvals[index]
        self._call_count += 1
        return GovernanceReview(
            approved=approved,
            feedback="" if approved else "Fake governance rejection for testing.",
        )


def _build_review_prompt(
    draft: RecommendationDraft, specialist_reports: list[SpecialistReport], ledger: EvidenceLedger
) -> str:
    return "\n".join(
        [
            "DRAFT RECOMMENDATION:",
            draft.model_dump_json(),
            "SPECIALIST REPORTS:",
            json.dumps(
                [
                    {"domain": r.domain.value, "status": r.status, "summary": r.summary}
                    for r in specialist_reports
                ]
            ),
            "EVIDENCE LEDGER:",
            json.dumps(
                [
                    {
                        "evidence_id": e.evidence_id,
                        "metric_name": e.metric_name,
                        "value": e.value,
                        "baseline_value": e.baseline_value,
                        "interpretation": e.interpretation,
                    }
                    for e in ledger.entries
                ],
                default=str,
            ),
        ]
    )


class AgentsSdkGovernanceAgentRunner:
    def __init__(
        self, model: OpenAIChatCompletionsModel, runtime: AgentRuntime | None = None
    ) -> None:
        self._runtime = runtime
        self._agent = Agent(
            name="governance-agent",
            instructions=GOVERNANCE_AGENT_SYSTEM_PROMPT,
            tools=[],
            output_type=GovernanceReview,
            model=model,
        )

    async def review(
        self,
        *,
        draft: RecommendationDraft,
        specialist_reports: list[SpecialistReport],
        ledger: EvidenceLedger,
    ) -> GovernanceReview:
        prompt = _build_review_prompt(draft, specialist_reports, ledger)
        if self._runtime is None:
            raise RuntimeError("Governance agent requires a configured bounded runtime.")
        output = await self._runtime.run(
            self._agent, prompt, output_contract="GovernanceReview"
        )
        if not isinstance(output, GovernanceReview):
            raise TypeError(f"Governance agent returned unexpected output type: {type(output)}")
        return output
