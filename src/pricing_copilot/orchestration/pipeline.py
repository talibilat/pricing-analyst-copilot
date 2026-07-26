from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agents import OpenAIChatCompletionsModel, trace
from openai import AsyncOpenAI

from pricing_copilot.analytics.calculators import MetricCalculationError
from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.config import (
    Settings,
    azure_openai_base_url,
    get_azure_openai_settings,
)
from pricing_copilot.contracts import (
    EvidenceDomain,
    GovernanceOutcome,
    PortfolioQuestion,
    Recommendation,
    Region,
    WorkflowResult,
)
from pricing_copilot.data.generation import DEFAULT_SCENARIO_SEED, DEFAULT_SCENARIO_VERSION
from pricing_copilot.data.repository import PortfolioDataRepository
from pricing_copilot.documents.retrieval import RetrievedDocument, retrieve_documents
from pricing_copilot.evidence.confidence import calculate_confidence
from pricing_copilot.evidence.fair_value import calculate_fair_value_status
from pricing_copilot.evidence.ledger import build_evidence_ledger
from pricing_copilot.evidence.models import EvidenceLedger
from pricing_copilot.evidence.policy import detect_material_evidence_issues
from pricing_copilot.governance.policy import validate_pre_synthesis_policy
from pricing_copilot.governance.registry import AGENT_REGISTRY_VERSION, require_approved_agent
from pricing_copilot.governance.security import quarantine_unsafe_documents
from pricing_copilot.observability.contracts import TraceEventKind
from pricing_copilot.observability.trace import (
    POLICY_VERSION,
    PROMPT_VERSION,
    TOOL_VERSION,
    WORKFLOW_NAME,
    TraceEventListener,
    WorkflowTraceRecorder,
    configure_local_agents_sdk_tracing,
)
from pricing_copilot.orchestration.governance_agent import (
    AgentsSdkGovernanceAgentRunner,
    GovernanceAgentRunner,
)
from pricing_copilot.orchestration.recommendation_agent import (
    AgentsSdkRecommendationAgentRunner,
    RecommendationAgentRunner,
)
from pricing_copilot.orchestration.runtime import AgentRuntime
from pricing_copilot.orchestration.specialists import SpecialistAgent, build_specialist_agents
from pricing_copilot.orchestration.supervisor import run_specialists, to_specialist_report
from pricing_copilot.recommendation.contracts import RecommendationDraft
from pricing_copilot.recommendation.governance import (
    GOVERNANCE_VERSION,
    RecommendationValidationError,
    validate_and_clamp_draft,
)
from pricing_copilot.versions import GOVERNED_RECOMMENDATION_VERSION
from pricing_copilot.workflow_common import (
    IMPLEMENTED_DATA_SCENARIOS,
    RETRIEVAL_QUERY,
    build_analytics,
    data_quality_investigation_result,
    missing_evidence_workflow_result,
)

SpecialistAgentsFactory = Callable[..., dict[EvidenceDomain, SpecialistAgent]]


@dataclass
class OrchestrationBundle:
    specialist_agents_factory: SpecialistAgentsFactory
    recommendation_agent: RecommendationAgentRunner
    governance_agent: GovernanceAgentRunner
    client: AsyncOpenAI | None = None
    runtime: AgentRuntime | None = None
    """Set only by get_default_orchestration - closed after each run so the underlying httpx
    connection pool never outlives the asyncio event loop it was created on."""


def get_default_orchestration(
    settings: Settings, *, event_listener: TraceEventListener | None = None
) -> OrchestrationBundle:
    configure_local_agents_sdk_tracing()
    recorder = WorkflowTraceRecorder(
        settings, _configuration_versions(settings), event_listener=event_listener
    )
    runtime = AgentRuntime(settings, recorder)
    azure_settings = get_azure_openai_settings()
    if not azure_settings.api_key or not azure_settings.endpoint:
        raise RuntimeError(
            "Azure OpenAI credentials are not configured "
            "(set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env)."
        )
    base_url = azure_openai_base_url(azure_settings.endpoint)
    client = AsyncOpenAI(api_key=azure_settings.api_key, base_url=base_url)
    deployment = azure_settings.chat_deployment or settings.model_name
    model = OpenAIChatCompletionsModel(model=deployment, openai_client=client)

    def factory(
        *, analytics: PortfolioAnalytics, documents: list[RetrievedDocument], region: Region
    ) -> dict[EvidenceDomain, SpecialistAgent]:
        return build_specialist_agents(
            analytics=analytics,
            documents=documents,
            region=region,
            model=model,
            runtime=runtime,
            tool_timeout_seconds=settings.tool_timeout_seconds,
        )

    return OrchestrationBundle(
        specialist_agents_factory=factory,
        recommendation_agent=AgentsSdkRecommendationAgentRunner(model, runtime),
        governance_agent=AgentsSdkGovernanceAgentRunner(model, runtime),
        client=client,
        runtime=runtime,
    )


def _configuration_versions(settings: Settings) -> dict[str, str | int | float | bool]:
    return {
        "model_name": settings.model_name,
        "prompt_version": PROMPT_VERSION,
        "agent_registry_version": AGENT_REGISTRY_VERSION,
        "tool_version": TOOL_VERSION,
        "dataset_version": DEFAULT_SCENARIO_VERSION,
        "scenario_seed": DEFAULT_SCENARIO_SEED,
        "governance_version": GOVERNANCE_VERSION,
        "recommendation_version": GOVERNED_RECOMMENDATION_VERSION,
        "policy_version": POLICY_VERSION,
        "recommendation_policy_version": POLICY_VERSION,
    }


def _validate(
    draft: RecommendationDraft,
    ledger: EvidenceLedger,
    documents: list[RetrievedDocument],
    settings: Settings,
) -> tuple[RecommendationDraft | None, str | None]:
    try:
        return (
            validate_and_clamp_draft(
                draft,
                ledger=ledger,
                documents=documents,
                max_movement_pct=settings.policy.max_price_movement_pct,
                policy=settings.policy,
            ),
            None,
        )
    except RecommendationValidationError as exc:
        return None, str(exc)


async def _run_governed_pipeline_async(
    question: PortfolioQuestion,
    settings: Settings,
    orchestration: OrchestrationBundle,
    recorder: WorkflowTraceRecorder,
) -> WorkflowResult:
    scenario = question.scenario
    if scenario is None:  # pragma: no cover - caller already filters via IMPLEMENTED_DATA_SCENARIOS
        raise ValueError("Governed workflow requires a scenario.")

    require_approved_agent(
        "portfolio-supervisor", tool_names=set(), output_contract="WorkflowResult"
    )
    recorder.event(
        TraceEventKind.ROUTING,
        "portfolio-supervisor",
        "started",
        details={"scenario": scenario.value},
    )

    repository = PortfolioDataRepository.from_persistent(
        scenario, settings.analytics_database_path
    )

    try:
        analytics = build_analytics(question, repository)
    except MetricCalculationError as exc:
        return data_quality_investigation_result(question, str(exc))

    retrieved_documents = retrieve_documents(
        scenario=scenario, region=question.region, query=RETRIEVAL_QUERY, top_k=6
    )
    documents, guardrail_findings = quarantine_unsafe_documents(retrieved_documents)
    for finding in guardrail_findings:
        recorder.event(
            TraceEventKind.GUARDRAIL,
            "untrusted_document",
            "blocked",
            details={"document_id": finding.document_id, "reason": finding.reason},
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
    for domain in specialist_agents:
        recorder.event(
            TraceEventKind.ROUTING,
            domain.value,
            "scheduled",
            details={"parallel": True},
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
    policy_issues = validate_pre_synthesis_policy(
        specialist_reports=specialist_reports,
        ledger=ledger,
        policy=settings.policy,
    )
    if policy_issues:
        for issue in policy_issues:
            recorder.event(
                TraceEventKind.GUARDRAIL,
                "evidence_policy",
                "blocked",
                details={"reason": issue},
            )
        return data_quality_investigation_result(question, "; ".join(policy_issues))

    recorder.event(
        TraceEventKind.GUARDRAIL,
        "evidence_policy",
        "passed",
        details={
            "minimum_source_types": settings.policy.minimum_source_types,
            "human_approval_required": settings.policy.require_human_approval,
        },
    )
    max_movement_pct = settings.policy.max_price_movement_pct

    draft = await orchestration.recommendation_agent.synthesize(
        specialist_reports=specialist_reports, ledger=ledger, max_movement_pct=max_movement_pct
    )
    validated, error = _validate(draft, ledger, documents, settings)

    revision_used = False
    if validated is None:
        revision_used = True
        draft = await orchestration.recommendation_agent.synthesize(
            specialist_reports=specialist_reports,
            ledger=ledger,
            max_movement_pct=max_movement_pct,
            revision_feedback=error,
        )
        validated, error = _validate(draft, ledger, documents, settings)
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
        validated, error = _validate(draft, ledger, documents, settings)
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
            "governance agent.",
            "Policy approval permits qualified human review only; it is not regulatory "
            "compliance and does not execute a pricing change.",
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


async def _run_and_close_client(
    question: PortfolioQuestion,
    settings: Settings,
    orchestration: OrchestrationBundle,
    recorder: WorkflowTraceRecorder,
) -> WorkflowResult:
    try:
        with trace(
            WORKFLOW_NAME,
            trace_id=recorder.trace_id,
            metadata=_configuration_versions(settings),
            disabled=not settings.agents_sdk_tracing_enabled,
        ):
            try:
                result = await asyncio.wait_for(
                    _run_governed_pipeline_async(question, settings, orchestration, recorder),
                    timeout=settings.max_workflow_seconds,
                )
            except TimeoutError:
                recorder.event(
                    TraceEventKind.FAILURE,
                    "workflow_timeout",
                    "failed_safe",
                    details={"limit_seconds": settings.max_workflow_seconds},
                )
                result = data_quality_investigation_result(
                    question,
                    f"workflow: total workflow time exceeded the configured "
                    f"{settings.max_workflow_seconds:g}-second limit.",
                )
            except Exception as exc:
                recorder.event(
                    TraceEventKind.FAILURE,
                    "workflow",
                    "failed_safe",
                    details={"error_type": type(exc).__name__},
                )
                result = data_quality_investigation_result(
                    question,
                    f"workflow: governed execution failed safely ({type(exc).__name__}).",
                )
        status = "safe_investigation" if result.missing_evidence else "completed"
        execution_trace = recorder.complete(status)
        return result.model_copy(update={"execution_trace": execution_trace})
    finally:
        if orchestration.client is not None:
            await orchestration.client.close()


def run_governed_portfolio_workflow(
    question: PortfolioQuestion,
    settings: Settings | None = None,
    *,
    orchestration: OrchestrationBundle | None = None,
    event_listener: TraceEventListener | None = None,
) -> WorkflowResult:
    from pricing_copilot.config import get_settings

    settings = settings or get_settings()
    if question.scenario not in IMPLEMENTED_DATA_SCENARIOS:
        return missing_evidence_workflow_result(question)
    if orchestration is None:
        scenario = question.scenario
        if scenario is None:
            return missing_evidence_workflow_result(question)
        preflight_repository = PortfolioDataRepository.from_persistent(
            scenario, settings.analytics_database_path
        )
        try:
            preflight_analytics = build_analytics(question, preflight_repository)
        except MetricCalculationError as exc:
            return data_quality_investigation_result(question, str(exc))
        preflight_documents, _ = quarantine_unsafe_documents(
            retrieve_documents(
                scenario=scenario,
                region=question.region,
                query=RETRIEVAL_QUERY,
                top_k=6,
            )
        )
        preflight_issues = detect_material_evidence_issues(
            preflight_documents,
            analysis_period_end=preflight_analytics.claims.period_end,
            max_evidence_age_days=settings.policy.max_evidence_age_days,
        )
        if preflight_issues:
            return data_quality_investigation_result(question, "; ".join(preflight_issues))
    if orchestration is not None:
        active = orchestration
    else:
        try:
            if event_listener is None:
                active = get_default_orchestration(settings)
            else:
                active = get_default_orchestration(settings, event_listener=event_listener)
        except RuntimeError as exc:
            return data_quality_investigation_result(
                question, f"workflow: model API is unavailable ({exc})."
            )
    recorder = (
        active.runtime.recorder
        if active.runtime is not None
        else WorkflowTraceRecorder(
            settings, _configuration_versions(settings), event_listener=event_listener
        )
    )
    configure_local_agents_sdk_tracing()
    return asyncio.run(_run_and_close_client(question, settings, active, recorder))
