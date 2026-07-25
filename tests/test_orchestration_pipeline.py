from datetime import date

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
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.governance_agent import FakeGovernanceAgentRunner
from pricing_copilot.orchestration.pipeline import OrchestrationBundle, run_governed_portfolio_workflow
from pricing_copilot.orchestration.recommendation_agent import FakeRecommendationAgentRunner
from pricing_copilot.orchestration.specialists import FakeSpecialistAgent
from pricing_copilot.recommendation.contracts import RecommendationDraft


def _question(scenario: ScenarioName) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)),
        scenario=scenario,
    )


def _fake_specialist_factory(**_kwargs):  # noqa: ANN003 - matches factory signature by design
    return {
        domain: FakeSpecialistAgent(SpecialistFindings(summary=f"{domain.value} summary ok"))
        for domain in EvidenceDomain
    }


def _bundle(*, recommendation=None, governance=None, specialist_factory=None) -> OrchestrationBundle:
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
    def _factory_that_must_not_be_called(**_kwargs):  # noqa: ANN003
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

    async def _tracking_synthesize(**kwargs):
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
    seen_kwargs: dict = {}

    class _SpyRecommendationAgent(FakeRecommendationAgentRunner):
        async def synthesize(self, **kwargs):  # noqa: ANN003
            seen_kwargs.update(kwargs)
            return await super().synthesize(**kwargs)

    run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(recommendation=_SpyRecommendationAgent()),
    )
    assert "analytics" not in seen_kwargs
    assert "documents" not in seen_kwargs
