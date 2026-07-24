from __future__ import annotations

from datetime import UTC, datetime

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
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.evidence.confidence import calculate_confidence
from pricing_copilot.evidence.fair_value import calculate_fair_value_status
from pricing_copilot.evidence.ledger import build_evidence_ledger
from pricing_copilot.recommendation.governance import validate_and_clamp_draft
from pricing_copilot.recommendation.synthesizer import RecommendationSynthesizer, get_default_synthesizer

REQUIRED_EVIDENCE_DOMAINS: tuple[EvidenceDomain, ...] = (
    EvidenceDomain.CLAIMS,
    EvidenceDomain.CONVERSION,
    EvidenceDomain.MARKET_INTELLIGENCE,
    EvidenceDomain.PRICING_HISTORY,
)

IMPLEMENTED_DATA_SCENARIOS: frozenset[ScenarioName] = frozenset({ScenarioName.CONTROLLED_INCREASE})

RETRIEVAL_QUERY = (
    "claims severity loss ratio conversion retention competitor pricing customer feedback broker "
    "price increase repair cost"
)


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


def _build_analytics(question: PortfolioQuestion, repository: PortfolioDataRepository) -> PortfolioAnalytics:
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


def _specialist_reports(
    question: PortfolioQuestion, analytics: PortfolioAnalytics, document_count: int
) -> list[SpecialistReport]:
    return [
        SpecialistReport(
            domain=EvidenceDomain.CLAIMS,
            status="completed",
            evidence_ids=[f"claims-{question.region.value}-{analytics.claims.period_end.isoformat()}"],
            summary=(
                f"Loss ratio moved from {analytics.claims.loss_ratio.baseline:.1%} to "
                f"{analytics.claims.loss_ratio.current:.1%} across "
                f"{analytics.claims.period_start.isoformat()} to "
                f"{analytics.claims.period_end.isoformat()}."
            ),
        ),
        SpecialistReport(
            domain=EvidenceDomain.CONVERSION,
            status="completed",
            evidence_ids=[
                f"conversion-{question.region.value}-{analytics.conversion.period_end.isoformat()}"
            ],
            summary=(
                "Quote-to-sale conversion moved from "
                f"{analytics.conversion.quote_to_sale_conversion.baseline:.1%} to "
                f"{analytics.conversion.quote_to_sale_conversion.current:.1%}."
            ),
        ),
        SpecialistReport(
            domain=EvidenceDomain.MARKET_INTELLIGENCE,
            status="completed",
            evidence_ids=[
                f"competitors-{question.region.value}-{analytics.competitors.period_end.isoformat()}"
            ],
            summary=(
                f"{len(analytics.competitors.competitors)} fictional competitors tracked and "
                f"{document_count} market-intelligence document(s) retrieved."
            ),
        ),
        SpecialistReport(
            domain=EvidenceDomain.PRICING_HISTORY,
            status="completed",
            evidence_ids=[
                f"pricing-history-{action.period.isoformat()}" for action in analytics.pricing_history
            ],
            summary=(
                f"{len(analytics.pricing_history)} previous pricing action(s) on record."
                if analytics.pricing_history
                else "No previous pricing actions on record for this scenario."
            ),
        ),
    ]


def _evidence_backed_workflow_result(
    question: PortfolioQuestion, settings: Settings, synthesizer: RecommendationSynthesizer | None
) -> WorkflowResult:
    scenario = question.scenario
    if scenario is None:
        raise ValueError("Evidence-backed workflow requires a scenario.")

    repository = PortfolioDataRepository.from_scenario(scenario)
    analytics = _build_analytics(question, repository)

    retrieved_documents = retrieve_documents(
        scenario=scenario, region=question.region, query=RETRIEVAL_QUERY, top_k=6
    )
    retrieved_at = datetime.now(UTC)
    ledger = build_evidence_ledger(
        analytics=analytics, documents=retrieved_documents, region=question.region, retrieved_at=retrieved_at
    )

    active_synthesizer = synthesizer or get_default_synthesizer(settings)
    draft = active_synthesizer.synthesize(
        analytics=analytics,
        ledger=ledger,
        documents=retrieved_documents,
        max_movement_pct=settings.policy.max_price_movement_pct,
    )
    validated = validate_and_clamp_draft(
        draft, ledger=ledger, max_movement_pct=settings.policy.max_price_movement_pct
    )

    confidence = calculate_confidence(
        ledger=ledger,
        documents=retrieved_documents,
        analytics=analytics,
        action=validated.action,
        analysis_period_end=analytics.claims.period_end,
    )
    fair_value_status, fair_value_follow_up = calculate_fair_value_status(
        action=validated.action,
        conversion_movement_pct=analytics.conversion.quote_to_sale_conversion.movement_pct,
        documents=retrieved_documents,
    )

    recommendation = Recommendation(
        action=validated.action,
        price_range=validated.price_range,
        rationale=validated.rationale,
        counter_evidence=validated.counter_evidence,
        conditions=validated.conditions,
        investigation_areas=validated.investigation_areas,
        cited_evidence_ids=validated.cited_evidence_ids,
        confidence=confidence,
        fair_value_status=fair_value_status,
        fair_value_follow_up=fair_value_follow_up,
    )

    governance_outcome = GovernanceOutcome(
        approved=True,
        reasons=[
            "Recommendation validated: all cited evidence ids exist in the ledger and the proposed "
            "range is within the configured policy limit."
        ],
    )

    return WorkflowResult(
        question=question,
        specialist_reports=_specialist_reports(question, analytics, len(retrieved_documents)),
        recommendation=recommendation,
        governance_outcome=governance_outcome,
        missing_evidence=[],
        analytics=analytics,
        evidence_ledger=ledger,
    )


def run_portfolio_workflow(
    question: PortfolioQuestion,
    settings: Settings | None = None,
    synthesizer: RecommendationSynthesizer | None = None,
) -> WorkflowResult:
    validate_portfolio_combination(question.product, question.region, question.segment)
    settings = settings or get_settings()

    if question.scenario in IMPLEMENTED_DATA_SCENARIOS:
        return _evidence_backed_workflow_result(question, settings, synthesizer)
    return _missing_evidence_workflow_result(question)
