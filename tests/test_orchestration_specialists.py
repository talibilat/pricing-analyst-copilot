import asyncio

from agents import OpenAIChatCompletionsModel

from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.contracts import EvidenceDomain, Region
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.specialists import (
    AgentsSdkSpecialistAgent,
    FakeSpecialistAgent,
    build_specialist_agents,
)


def test_fake_specialist_agent_returns_configured_findings() -> None:
    findings = SpecialistFindings(summary="Loss ratio rose.", cited_evidence_ids=["claims-x"])
    agent = FakeSpecialistAgent(findings)
    assert asyncio.run(agent.analyze()) is findings


def test_build_specialist_agents_returns_one_agent_per_required_domain(
    controlled_increase_analytics: PortfolioAnalytics,
    controlled_increase_documents: list[RetrievedDocument],
    azure_chat_model: OpenAIChatCompletionsModel,
) -> None:
    agents = build_specialist_agents(
        analytics=controlled_increase_analytics,
        documents=controlled_increase_documents,
        region=Region.NORTH_WEST,
        model=azure_chat_model,
    )
    assert set(agents) == {
        EvidenceDomain.CLAIMS,
        EvidenceDomain.CONVERSION,
        EvidenceDomain.MARKET_INTELLIGENCE,
        EvidenceDomain.PRICING_HISTORY,
    }


def test_each_specialist_agent_has_exactly_its_domain_tools(
    controlled_increase_analytics: PortfolioAnalytics,
    controlled_increase_documents: list[RetrievedDocument],
    azure_chat_model: OpenAIChatCompletionsModel,
) -> None:
    agents = build_specialist_agents(
        analytics=controlled_increase_analytics,
        documents=controlled_increase_documents,
        region=Region.NORTH_WEST,
        model=azure_chat_model,
    )

    def tool_names(domain: EvidenceDomain) -> set[str]:
        agent = agents[domain]
        assert isinstance(agent, AgentsSdkSpecialistAgent)
        return {t.name for t in agent.agent.tools}

    assert tool_names(EvidenceDomain.CLAIMS) == {"get_claims_metrics"}
    assert tool_names(EvidenceDomain.CONVERSION) == {"get_conversion_metrics"}
    assert tool_names(EvidenceDomain.MARKET_INTELLIGENCE) == {
        "get_competitor_metrics",
        "get_market_intelligence_documents",
    }
    assert tool_names(EvidenceDomain.PRICING_HISTORY) == {"get_pricing_history"}
