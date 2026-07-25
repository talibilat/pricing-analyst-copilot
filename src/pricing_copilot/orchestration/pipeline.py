from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from pricing_copilot.analytics.calculators import MetricCalculationError
from pricing_copilot.config import Settings, get_azure_openai_settings
from pricing_copilot.contracts import (
    EvidenceDomain,
    GovernanceOutcome,
    PortfolioQuestion,
    Recommendation,
    WorkflowResult,
)
from pricing_copilot.data.repository import PortfolioDataRepository
from pricing_copilot.documents.retrieval import RetrievedDocument, retrieve_documents
from pricing_copilot.evidence.confidence import calculate_confidence
from pricing_copilot.evidence.fair_value import calculate_fair_value_status
from pricing_copilot.evidence.ledger import build_evidence_ledger
from pricing_copilot.evidence.policy import detect_material_evidence_issues
from pricing_copilot.orchestration.governance_agent import (
    AgentsSdkGovernanceAgentRunner,
    GovernanceAgentRunner,
)
from pricing_copilot.orchestration.recommendation_agent import (
    AgentsSdkRecommendationAgentRunner,
    RecommendationAgentRunner,
)
from pricing_copilot.orchestration.specialists import SpecialistAgent, build_specialist_agents
from pricing_copilot.orchestration.supervisor import run_specialists, to_specialist_report
from pricing_copilot.recommendation.contracts import RecommendationDraft
from pricing_copilot.recommendation.governance import (
    RecommendationValidationError,
    validate_and_clamp_draft,
)
from pricing_copilot.workflow_common import (
    IMPLEMENTED_DATA_SCENARIOS,
    RETRIEVAL_QUERY,
    build_analytics,
    data_quality_investigation_result,
    missing_evidence_workflow_result,
)

set_tracing_disabled(True)

GOVERNED_RECOMMENDATION_VERSION = "governed-multi-agent-v1"

SpecialistAgentsFactory = Callable[..., dict[EvidenceDomain, SpecialistAgent]]


@dataclass
class OrchestrationBundle:
    specialist_agents_factory: SpecialistAgentsFactory
    recommendation_agent: RecommendationAgentRunner
    governance_agent: GovernanceAgentRunner


def get_default_orchestration(settings: Settings) -> OrchestrationBundle:
    azure_settings = get_azure_openai_settings()
    if not azure_settings.api_key or not azure_settings.endpoint:
        raise RuntimeError(
            "Azure OpenAI credentials are not configured "
            "(set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env)."
        )
    base_url = azure_settings.endpoint.rstrip("/") + "/openai/v1"
    client = AsyncOpenAI(api_key=azure_settings.api_key, base_url=base_url)
    deployment = azure_settings.chat_deployment or settings.model_name
    model = OpenAIChatCompletionsModel(model=deployment, openai_client=client)

    def factory(
        *, analytics, documents: list[RetrievedDocument], region
    ) -> dict[EvidenceDomain, SpecialistAgent]:
        return build_specialist_agents(
            analytics=analytics, documents=documents, region=region, model=model
        )

    return OrchestrationBundle(
        specialist_agents_factory=factory,
        recommendation_agent=AgentsSdkRecommendationAgentRunner(model),
        governance_agent=AgentsSdkGovernanceAgentRunner(model),
    )


def _validate(
    draft: RecommendationDraft, ledger, documents, max_movement_pct: float
) -> tuple[RecommendationDraft | None, str | None]:
    try:
        return (
            validate_and_clamp_draft(
                draft, ledger=ledger, documents=documents, max_movement_pct=max_movement_pct
            ),
            None,
        )
    except RecommendationValidationError as exc:
        return None, str(exc)


async def _run_governed_pipeline_async(
    question: PortfolioQuestion, settings: Settings, orchestration: OrchestrationBundle
) -> WorkflowResult:
    scenario = question.scenario
    if scenario is None:  # pragma: no cover - caller already filters via IMPLEMENTED_DATA_SCENARIOS
        raise ValueError("Governed workflow requires a scenario.")

    repository = PortfolioDataRepository.from_scenario(scenario)

    try:
        analytics = build_analytics(question, repository)
    except MetricCalculationError as exc:
        return data_quality_investigation_result(question, str(exc))

    documents = retrieve_documents(
        scenario=scenario, region=question.region, query=RETRIEVAL_QUERY, top_k=6
    )

    material_issues = detect_material_evidence_issues(
        documents,
        analysis_period_end=analytics.claims.period_end,
        max_evidence_age_days=settings.policy.max_evidence_age_days,
    )
    if material_issues:
        return data_quality_investigation_result(question, "; ".join(material_issues))

    specialist_agents = orchestration.specialist_agents_factory(
        analytics=analytics, documents=documents, region=question.region
    )
    findings_by_domain, failed_domains = await run_specialists(specialist_agents)
    if failed_domains:
        failed_names = ", ".join(d.value for d in failed_domains)
        return data_quality_investigation_result(
            question, f"{failed_domains[0].value}: specialist agent failed ({failed_names})."
        )

    specialist_reports = [
        to_specialist_report(domain, findings) for domain, findings in findings_by_domain.items()
    ]

    ledger = build_evidence_ledger(
        analytics=analytics,
        documents=documents,
        region=question.region,
        retrieved_at=datetime.now(UTC),
    )
    max_movement_pct = settings.policy.max_price_movement_pct

    draft = await orchestration.recommendation_agent.synthesize(
        specialist_reports=specialist_reports, ledger=ledger, max_movement_pct=max_movement_pct
    )
    validated, error = _validate(draft, ledger, documents, max_movement_pct)

    revision_used = False
    if validated is None:
        revision_used = True
        draft = await orchestration.recommendation_agent.synthesize(
            specialist_reports=specialist_reports,
            ledger=ledger,
            max_movement_pct=max_movement_pct,
            revision_feedback=error,
        )
        validated, error = _validate(draft, ledger, documents, max_movement_pct)
        if validated is None:
            return data_quality_investigation_result(
                question,
                f"Recommendation failed deterministic governance validation twice: {error}",
            )

    review = await orchestration.governance_agent.review(
        draft=validated, specialist_reports=specialist_reports, ledger=ledger
    )
    if not review.approved:
        if revision_used:
            return data_quality_investigation_result(
                question,
                "Governance agent rejected the recommendation and the bounded revision budget "
                f"was already used: {review.feedback}",
            )
        draft = await orchestration.recommendation_agent.synthesize(
            specialist_reports=specialist_reports,
            ledger=ledger,
            max_movement_pct=max_movement_pct,
            revision_feedback=review.feedback,
        )
        validated, error = _validate(draft, ledger, documents, max_movement_pct)
        if validated is None:
            return data_quality_investigation_result(
                question,
                f"Revision after governance rejection failed deterministic validation: {error}",
            )
        review = await orchestration.governance_agent.review(
            draft=validated, specialist_reports=specialist_reports, ledger=ledger
        )
        if not review.approved:
            return data_quality_investigation_result(
                question,
                f"Governance agent rejected the revised recommendation: {review.feedback}",
            )

    confidence = calculate_confidence(
        ledger=ledger,
        documents=documents,
        analytics=analytics,
        action=validated.action,
        analysis_period_end=analytics.claims.period_end,
    )
    fair_value_status, fair_value_follow_up = calculate_fair_value_status(
        action=validated.action,
        conversion_movement_pct=analytics.conversion.quote_to_sale_conversion.movement_pct,
        documents=documents,
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
            "Recommendation validated deterministically and approved by the independent "
            "governance agent."
        ],
    )
    return WorkflowResult(
        question=question,
        specialist_reports=specialist_reports,
        recommendation=recommendation,
        governance_outcome=governance_outcome,
        missing_evidence=[],
        analytics=analytics,
        evidence_ledger=ledger,
    )


def run_governed_portfolio_workflow(
    question: PortfolioQuestion,
    settings: Settings | None = None,
    *,
    orchestration: OrchestrationBundle | None = None,
) -> WorkflowResult:
    from pricing_copilot.config import get_settings

    settings = settings or get_settings()
    if question.scenario not in IMPLEMENTED_DATA_SCENARIOS:
        return missing_evidence_workflow_result(question)
    active = orchestration or get_default_orchestration(settings)
    return asyncio.run(_run_governed_pipeline_async(question, settings, active))
