import asyncio
from datetime import date
from typing import Any
from unittest.mock import patch

from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    PriceRange,
    Product,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.governance_agent import (
    FakeGovernanceAgentRunner,
    GovernanceAgentRunner,
)
from pricing_copilot.orchestration.pipeline import (
    OrchestrationBundle,
    run_governed_portfolio_workflow,
)
from pricing_copilot.orchestration.recommendation_agent import (
    FakeRecommendationAgentRunner,
    RecommendationAgentRunner,
)
from pricing_copilot.orchestration.specialists import FakeSpecialistAgent, SpecialistAgent
from pricing_copilot.recommendation.contracts import RecommendationDraft


def _question(scenario: ScenarioName) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)),
        scenario=scenario,
    )


def _fake_specialist_factory(
    *, analytics: PortfolioAnalytics, documents: list[RetrievedDocument], region: Region
) -> dict[EvidenceDomain, SpecialistAgent]:
    return {
        domain: FakeSpecialistAgent(SpecialistFindings(summary=f"{domain.value} summary ok"))
        for domain in EvidenceDomain
    }


def _bundle(
    *,
    recommendation: RecommendationAgentRunner | None = None,
    governance: GovernanceAgentRunner | None = None,
    specialist_factory: Any = None,
) -> OrchestrationBundle:
    return OrchestrationBundle(
        specialist_agents_factory=specialist_factory or _fake_specialist_factory,
        recommendation_agent=recommendation or FakeRecommendationAgentRunner(),
        governance_agent=governance or FakeGovernanceAgentRunner(),
    )


def test_governed_controlled_increase_produces_typed_reports_for_every_domain() -> None:
    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE), orchestration=_bundle()
    )
    assert {r.domain for r in result.specialist_reports} == set(EvidenceDomain)
    assert all(r.status == "completed" for r in result.specialist_reports)
    assert result.recommendation.action is RecommendationAction.INCREASE
    assert result.evidence_ledger is not None
    assert set(result.recommendation.cited_evidence_ids).issubset(result.evidence_ledger.ids())


def test_governed_retention_concern_holds() -> None:
    result = run_governed_portfolio_workflow(
        _question(ScenarioName.RETENTION_CONCERN), orchestration=_bundle()
    )
    assert result.recommendation.action in (
        RecommendationAction.HOLD,
        RecommendationAction.DECREASE,
    )


def test_governed_conflicting_evidence_investigates_without_calling_any_agent() -> None:
    def _factory_that_must_not_be_called(**_kwargs: Any) -> dict[EvidenceDomain, SpecialistAgent]:
        raise AssertionError("Specialist agents must not be invoked when the gate short-circuits.")

    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONFLICTING_EVIDENCE),
        orchestration=_bundle(specialist_factory=_factory_that_must_not_be_called),
    )
    assert result.recommendation.action is RecommendationAction.INVESTIGATE


def test_governance_rejection_triggers_exactly_one_bounded_revision_then_succeeds() -> None:
    revised_draft = RecommendationDraft(
        action=RecommendationAction.HOLD,
        rationale="Revised: holding given the specialist reports.",
    )
    recommendation = FakeRecommendationAgentRunner()
    call_log: list[str | None] = []
    original_synthesize = recommendation.synthesize

    async def _tracking_synthesize(**kwargs: Any) -> RecommendationDraft:
        call_log.append(kwargs.get("revision_feedback"))
        if kwargs.get("revision_feedback") is not None:
            return revised_draft
        return await original_synthesize(**kwargs)

    recommendation.synthesize = _tracking_synthesize  # type: ignore[method-assign]
    governance = FakeGovernanceAgentRunner(approvals=[False, True])

    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(recommendation=recommendation, governance=governance),
    )

    assert call_log == [None, "Fake governance rejection for testing."]
    assert result.recommendation.action is RecommendationAction.HOLD
    assert result.recommendation.rationale == revised_draft.rationale


def test_repeated_governance_rejection_falls_back_to_investigate_not_an_unbounded_loop() -> None:
    governance = FakeGovernanceAgentRunner(approvals=[False])

    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(governance=governance),
    )

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert governance._call_count == 2  # noqa: SLF001 - white-box proof of the revision bound


def test_deterministic_validation_failure_also_consumes_the_one_bounded_revision() -> None:
    bad_draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=2.0, upper_pct=3.0),
        rationale="Claims fell 99.0%, an unsupported figure.",
        cited_evidence_ids=[],
    )
    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(recommendation=FakeRecommendationAgentRunner(draft=bad_draft)),
    )
    assert result.recommendation.action is RecommendationAction.INVESTIGATE


def test_recommendation_agent_never_receives_analytics_or_documents_kwarg() -> None:
    seen_kwargs: dict[str, Any] = {}

    class _SpyRecommendationAgent(FakeRecommendationAgentRunner):
        async def synthesize(self, **kwargs: Any) -> RecommendationDraft:
            seen_kwargs.update(kwargs)
            return await super().synthesize(**kwargs)

    run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(recommendation=_SpyRecommendationAgent()),
    )
    assert "analytics" not in seen_kwargs
    assert "documents" not in seen_kwargs


def test_total_workflow_timeout_fails_safe_without_unbounded_wait() -> None:
    class _SlowSpecialist(FakeSpecialistAgent):
        async def analyze(self) -> SpecialistFindings:
            await asyncio.sleep(0.1)
            return await super().analyze()

    def _slow_factory(
        *, analytics: PortfolioAnalytics, documents: list[RetrievedDocument], region: Region
    ) -> dict[EvidenceDomain, SpecialistAgent]:
        return {
            domain: _SlowSpecialist(SpecialistFindings(summary="eventually"))
            for domain in EvidenceDomain
        }

    settings = Settings(max_workflow_seconds=0.01, local_tracing_enabled=False)
    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        settings,
        orchestration=_bundle(specialist_factory=_slow_factory),
    )
    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert "workflow time exceeded" in result.recommendation.rationale
    assert result.execution_trace is not None
    assert result.execution_trace.status == "safe_investigation"


def test_prompt_injection_guardrail_is_visible_and_quarantined_from_the_ledger() -> None:
    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        Settings(local_tracing_enabled=False),
        orchestration=_bundle(),
    )
    assert result.execution_trace is not None
    blocked = [
        event
        for event in result.execution_trace.events
        if event.name == "untrusted_document" and event.status == "blocked"
    ]
    assert blocked
    assert result.evidence_ledger is not None
    assert "doc-market-2025-11-adversarial" not in result.evidence_ledger.ids()
    versions = result.execution_trace.configuration_versions
    assert versions["model_name"]
    assert versions["prompt_version"]
    assert versions["agent_registry_version"]
    assert versions["tool_version"]
    assert versions["dataset_version"]
    assert versions["recommendation_policy_version"]


def test_missing_credentials_produces_a_safe_investigate_result_not_a_crash() -> None:
    with patch(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        side_effect=RuntimeError("Azure OpenAI credentials are not configured."),
    ):
        result = run_governed_portfolio_workflow(_question(ScenarioName.CONTROLLED_INCREASE))

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.missing_evidence
    assert "workflow:" in result.missing_evidence[0].reason
    assert "unavailable" in result.missing_evidence[0].reason.lower()


def test_recommendation_agent_raising_a_model_behavior_error_fails_safely() -> None:
    from agents.exceptions import ModelBehaviorError

    class _BrokenRecommendationAgent(FakeRecommendationAgentRunner):
        async def synthesize(self, **_kwargs: Any) -> RecommendationDraft:
            raise ModelBehaviorError("invalid structured output")

    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(recommendation=_BrokenRecommendationAgent()),
    )
    assert result.recommendation.action is RecommendationAction.INVESTIGATE
