from __future__ import annotations

from pricing_copilot.analytics.calculators import (
    calculate_claims_metrics,
    calculate_competitor_metrics,
    calculate_conversion_metrics,
    summarize_pricing_history,
)
from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.contracts import (
    EvidenceDomain,
    GovernanceOutcome,
    MissingEvidence,
    PortfolioQuestion,
    Recommendation,
    RecommendationAction,
    ScenarioName,
    SpecialistReport,
    WorkflowResult,
)
from pricing_copilot.data.repository import PortfolioDataRepository

REQUIRED_EVIDENCE_DOMAINS: tuple[EvidenceDomain, ...] = (
    EvidenceDomain.CLAIMS,
    EvidenceDomain.CONVERSION,
    EvidenceDomain.MARKET_INTELLIGENCE,
    EvidenceDomain.PRICING_HISTORY,
)

IMPLEMENTED_DATA_SCENARIOS: frozenset[ScenarioName] = frozenset(
    {
        ScenarioName.CONTROLLED_INCREASE,
        ScenarioName.RETENTION_CONCERN,
        ScenarioName.CONFLICTING_EVIDENCE,
    }
)

_DOMAIN_ERROR_PREFIXES: dict[str, EvidenceDomain] = {
    "claims": EvidenceDomain.CLAIMS,
    "conversion": EvidenceDomain.CONVERSION,
    "competitors": EvidenceDomain.MARKET_INTELLIGENCE,
    "market_intelligence": EvidenceDomain.MARKET_INTELLIGENCE,
    "pricing_history": EvidenceDomain.PRICING_HISTORY,
}

RETRIEVAL_QUERY = (
    "claims severity loss ratio conversion retention competitor pricing customer feedback broker "
    "price increase repair cost"
)


def domain_from_error_message(message: str) -> EvidenceDomain:
    prefix = message.split(":", 1)[0].strip()
    for key, domain in _DOMAIN_ERROR_PREFIXES.items():
        if prefix.startswith(key):
            return domain
    return EvidenceDomain.CLAIMS


def missing_evidence_reason(domain: EvidenceDomain) -> str:
    return (
        f"No {domain.value} evidence source is connected in this prototype slice yet, "
        "so no claim in this domain can be supported."
    )


def missing_evidence_workflow_result(question: PortfolioQuestion) -> WorkflowResult:
    missing_evidence = [
        MissingEvidence(domain=domain, reason=missing_evidence_reason(domain))
        for domain in REQUIRED_EVIDENCE_DOMAINS
    ]
    specialist_reports = [
        SpecialistReport(
            domain=domain,
            status="missing_evidence",
            evidence_ids=[],
            summary=f"{domain.value} specialist has no evidence source connected yet.",
            missing_evidence=[
                MissingEvidence(domain=domain, reason=missing_evidence_reason(domain))
            ],
        )
        for domain in REQUIRED_EVIDENCE_DOMAINS
    ]
    recommendation = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        rationale=(
            "Investigation is required: no evidence sources are connected yet for this "
            "prototype slice, so no pricing claim can be supported."
        ),
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


def data_quality_investigation_result(question: PortfolioQuestion, reason: str) -> WorkflowResult:
    domain = domain_from_error_message(reason)
    missing_evidence = [MissingEvidence(domain=domain, reason=reason)]
    specialist_reports = [
        SpecialistReport(
            domain=domain,
            status="error",
            evidence_ids=[],
            summary=reason,
            missing_evidence=missing_evidence,
        )
    ]
    recommendation = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        rationale=(
            f"Investigation is required: {reason} This gap is material enough that no "
            "pricing claim can be safely supported for this period."
        ),
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


def build_analytics(
    question: PortfolioQuestion, repository: PortfolioDataRepository
) -> PortfolioAnalytics:
    claims_records = repository.fetch_claims(question.product, question.region, question.segment)
    conversion_records = repository.fetch_conversion(question.product, question.region)
    competitor_records = repository.fetch_competitors(question.region)
    pricing_history_records = repository.fetch_pricing_history(
        question.product, question.region, question.segment
    )
    return PortfolioAnalytics(
        claims=calculate_claims_metrics(claims_records),
        conversion=calculate_conversion_metrics(conversion_records, question.segment),
        competitors=calculate_competitor_metrics(competitor_records),
        pricing_history=summarize_pricing_history(pricing_history_records),
    )
