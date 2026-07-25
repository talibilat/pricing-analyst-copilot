from __future__ import annotations

from datetime import UTC, datetime

from pricing_copilot.analytics.calculators import MetricCalculationError
from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.catalog import validate_portfolio_combination
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    EvidenceDomain,
    GovernanceOutcome,
    PortfolioQuestion,
    Recommendation,
    SpecialistReport,
    WorkflowResult,
)
from pricing_copilot.data.repository import PortfolioDataRepository
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.evidence.confidence import calculate_confidence
from pricing_copilot.evidence.fair_value import calculate_fair_value_status
from pricing_copilot.evidence.ledger import build_evidence_ledger
from pricing_copilot.evidence.policy import detect_material_evidence_issues
from pricing_copilot.orchestration.pipeline import run_governed_portfolio_workflow
from pricing_copilot.recommendation.governance import validate_and_clamp_draft
from pricing_copilot.recommendation.synthesizer import (
    RecommendationSynthesizer,
    get_default_synthesizer,
)
from pricing_copilot.workflow_common import (
    IMPLEMENTED_DATA_SCENARIOS,
    RETRIEVAL_QUERY,
    build_analytics,
    data_quality_investigation_result,
    missing_evidence_workflow_result,
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
                f"pricing-history-{action.period.isoformat()}"
                for action in analytics.pricing_history
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

    try:
        analytics = build_analytics(question, repository)
    except MetricCalculationError as exc:
        return data_quality_investigation_result(question, str(exc))

    retrieved_documents = retrieve_documents(
        scenario=scenario, region=question.region, query=RETRIEVAL_QUERY, top_k=6
    )

    material_issues = detect_material_evidence_issues(
        retrieved_documents,
        analysis_period_end=analytics.claims.period_end,
        max_evidence_age_days=settings.policy.max_evidence_age_days,
    )
    if material_issues:
        return data_quality_investigation_result(question, "; ".join(material_issues))

    retrieved_at = datetime.now(UTC)
    ledger = build_evidence_ledger(
        analytics=analytics,
        documents=retrieved_documents,
        region=question.region,
        retrieved_at=retrieved_at,
    )

    active_synthesizer = synthesizer or get_default_synthesizer(settings)
    draft = active_synthesizer.synthesize(
        analytics=analytics,
        ledger=ledger,
        documents=retrieved_documents,
        max_movement_pct=settings.policy.max_price_movement_pct,
    )
    validated = validate_and_clamp_draft(
        draft,
        ledger=ledger,
        documents=retrieved_documents,
        max_movement_pct=settings.policy.max_price_movement_pct,
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


def run_baseline_portfolio_workflow(
    question: PortfolioQuestion,
    settings: Settings | None = None,
    synthesizer: RecommendationSynthesizer | None = None,
) -> WorkflowResult:
    """The original single-agent baseline pipeline. Retained for fallback and side-by-side
    benchmarking against the governed multi-agent pipeline (see run_governed_portfolio_workflow)."""
    validate_portfolio_combination(question.product, question.region, question.segment)
    settings = settings or get_settings()

    if question.scenario in IMPLEMENTED_DATA_SCENARIOS:
        return _evidence_backed_workflow_result(question, settings, synthesizer)
    return missing_evidence_workflow_result(question)


def run_portfolio_workflow(
    question: PortfolioQuestion,
    settings: Settings | None = None,
    synthesizer: RecommendationSynthesizer | None = None,
    *,
    use_baseline: bool = False,
) -> WorkflowResult:
    """Public entry point used by the API, CLI, and Streamlit interface. Defaults to the
    governed multi-agent pipeline; set use_baseline=True (or pass an explicit synthesizer) to
    run the single-agent baseline instead, for fallback or side-by-side benchmarking."""
    if use_baseline or synthesizer is not None:
        return run_baseline_portfolio_workflow(question, settings, synthesizer)

    validate_portfolio_combination(question.product, question.region, question.segment)
    return run_governed_portfolio_workflow(question, settings)
