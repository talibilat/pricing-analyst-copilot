from __future__ import annotations

from pricing_copilot.analytics.calculators import (
    calculate_claims_metrics,
    calculate_competitor_metrics,
    calculate_conversion_metrics,
    summarize_pricing_history,
)
from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.catalog import validate_portfolio_combination
from pricing_copilot.config import Settings, get_settings
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

IMPLEMENTED_DATA_SCENARIOS: frozenset[ScenarioName] = frozenset({ScenarioName.CONTROLLED_INCREASE})


def _missing_evidence_reason(domain: EvidenceDomain) -> str:
    return (
        f"No {domain.value} evidence source is connected in this prototype slice yet, "
        "so no claim in this domain can be supported."
    )


def _missing_evidence_workflow_result(question: PortfolioQuestion) -> WorkflowResult:
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
        analytics=None,
    )


def _evidence_backed_workflow_result(question: PortfolioQuestion) -> WorkflowResult:
    scenario = question.scenario
    if scenario is None:
        raise ValueError("Evidence-backed workflow requires a scenario.")

    repository = PortfolioDataRepository.from_scenario(scenario)

    claims_records = repository.fetch_claims(question.product, question.region, question.segment)
    conversion_records = repository.fetch_conversion(question.product, question.region)
    competitor_records = repository.fetch_competitors(question.region)
    pricing_history_records = repository.fetch_pricing_history(
        question.product, question.region, question.segment
    )

    claims_metrics = calculate_claims_metrics(claims_records)
    conversion_metrics = calculate_conversion_metrics(conversion_records, question.segment)
    competitor_metrics = calculate_competitor_metrics(competitor_records)
    pricing_history = summarize_pricing_history(pricing_history_records)

    analytics = PortfolioAnalytics(
        claims=claims_metrics,
        conversion=conversion_metrics,
        competitors=competitor_metrics,
        pricing_history=pricing_history,
    )

    specialist_reports = [
        SpecialistReport(
            domain=EvidenceDomain.CLAIMS,
            status="completed",
            evidence_ids=[f"claims-{question.region.value}-{claims_metrics.period_end.isoformat()}"],
            summary=(
                f"Loss ratio moved from {claims_metrics.loss_ratio.baseline:.1%} to "
                f"{claims_metrics.loss_ratio.current:.1%} across "
                f"{claims_metrics.period_start.isoformat()} to {claims_metrics.period_end.isoformat()}."
            ),
        ),
        SpecialistReport(
            domain=EvidenceDomain.CONVERSION,
            status="completed",
            evidence_ids=[
                f"conversion-{question.region.value}-{conversion_metrics.period_end.isoformat()}"
            ],
            summary=(
                "Quote-to-sale conversion moved from "
                f"{conversion_metrics.quote_to_sale_conversion.baseline:.1%} to "
                f"{conversion_metrics.quote_to_sale_conversion.current:.1%}."
            ),
        ),
        SpecialistReport(
            domain=EvidenceDomain.MARKET_INTELLIGENCE,
            status="completed",
            evidence_ids=[
                f"competitors-{question.region.value}-{competitor_metrics.period_end.isoformat()}"
            ],
            summary=(
                f"{len(competitor_metrics.competitors)} fictional competitors tracked across "
                f"{competitor_metrics.period_start.isoformat()} to "
                f"{competitor_metrics.period_end.isoformat()}."
            ),
        ),
        SpecialistReport(
            domain=EvidenceDomain.PRICING_HISTORY,
            status="completed",
            evidence_ids=[f"pricing-history-{action.period.isoformat()}" for action in pricing_history],
            summary=(
                f"{len(pricing_history)} previous pricing action(s) on record."
                if pricing_history
                else "No previous pricing actions on record for this scenario."
            ),
        ),
    ]

    recommendation = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        price_range=None,
        rationale=(
            "Evidence has been gathered for all specialist domains, but recommendation "
            "synthesis is not implemented in this build yet, so no pricing direction can "
            "be proposed."
        ),
        cited_evidence_ids=[
            report.evidence_ids[0] for report in specialist_reports if report.evidence_ids
        ],
        confidence=None,
    )
    governance_outcome = GovernanceOutcome(
        approved=True,
        reasons=[
            "No pricing direction is proposed while recommendation synthesis is unimplemented."
        ],
    )

    return WorkflowResult(
        question=question,
        specialist_reports=specialist_reports,
        recommendation=recommendation,
        governance_outcome=governance_outcome,
        missing_evidence=[],
        analytics=analytics,
    )


def run_portfolio_workflow(
    question: PortfolioQuestion, settings: Settings | None = None
) -> WorkflowResult:
    validate_portfolio_combination(question.product, question.region, question.segment)
    settings = settings or get_settings()

    if question.scenario in IMPLEMENTED_DATA_SCENARIOS:
        return _evidence_backed_workflow_result(question)
    return _missing_evidence_workflow_result(question)
