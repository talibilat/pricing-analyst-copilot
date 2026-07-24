from __future__ import annotations

from pricing_copilot.catalog import validate_portfolio_combination
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    EvidenceDomain,
    GovernanceOutcome,
    MissingEvidence,
    PortfolioQuestion,
    Recommendation,
    RecommendationAction,
    SpecialistReport,
    WorkflowResult,
)

REQUIRED_EVIDENCE_DOMAINS: tuple[EvidenceDomain, ...] = (
    EvidenceDomain.CLAIMS,
    EvidenceDomain.CONVERSION,
    EvidenceDomain.MARKET_INTELLIGENCE,
    EvidenceDomain.PRICING_HISTORY,
)


def _missing_evidence_reason(domain: EvidenceDomain) -> str:
    return (
        f"No {domain.value} evidence source is connected in this prototype slice yet, "
        "so no claim in this domain can be supported."
    )


def run_portfolio_workflow(
    question: PortfolioQuestion, settings: Settings | None = None
) -> WorkflowResult:
    validate_portfolio_combination(question.product, question.region, question.segment)
    settings = settings or get_settings()

    missing_evidence = [
        MissingEvidence(domain=domain, reason=_missing_evidence_reason(domain))
        for domain in REQUIRED_EVIDENCE_DOMAINS
    ]
    specialist_reports = [
        SpecialistReport(
            domain=domain,
            status="missing_evidence",
            evidence_ids=[],
            summary=f"{domain.value} specialist has no evidence source connected yet.",
            missing_evidence=[
                MissingEvidence(domain=domain, reason=_missing_evidence_reason(domain))
            ],
        )
        for domain in REQUIRED_EVIDENCE_DOMAINS
    ]
    recommendation = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        price_range=None,
        rationale=(
            "Investigation is required: no evidence sources are connected yet for this "
            "prototype slice, so no pricing claim can be supported."
        ),
        cited_evidence_ids=[],
        confidence=None,
    )
    governance_outcome = GovernanceOutcome(
        approved=True,
        reasons=[
            "An investigate outcome proposes no price movement and cites no unsupported claims."
        ],
    )

    return WorkflowResult(
        question=question,
        specialist_reports=specialist_reports,
        recommendation=recommendation,
        governance_outcome=governance_outcome,
        missing_evidence=missing_evidence,
    )
