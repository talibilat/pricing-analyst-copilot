import asyncio

from pricing_copilot.contracts import EvidenceDomain, Region
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.specialists import FakeSpecialistAgent, build_specialist_agents


def test_fake_specialist_agent_returns_configured_findings() -> None:
    findings = SpecialistFindings(summary="Loss ratio rose.", cited_evidence_ids=["claims-x"])
    agent = FakeSpecialistAgent(findings)
    assert asyncio.run(agent.analyze()) is findings


def test_build_specialist_agents_returns_one_agent_per_required_domain(
    controlled_increase_analytics, controlled_increase_documents, azure_chat_model
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
    controlled_increase_analytics, controlled_increase_documents, azure_chat_model
) -> None:
    agents = build_specialist_agents(
        analytics=controlled_increase_analytics,
        documents=controlled_increase_documents,
        region=Region.NORTH_WEST,
        model=azure_chat_model,
    )
    claims_tool_names = {t.name for t in agents[EvidenceDomain.CLAIMS].agent.tools}
    assert claims_tool_names == {"get_claims_metrics"}

    conversion_tool_names = {t.name for t in agents[EvidenceDomain.CONVERSION].agent.tools}
    assert conversion_tool_names == {"get_conversion_metrics"}

    market_tool_names = {t.name for t in agents[EvidenceDomain.MARKET_INTELLIGENCE].agent.tools}
    assert market_tool_names == {"get_competitor_metrics", "get_market_intelligence_documents"}

    pricing_history_tool_names = {
        t.name for t in agents[EvidenceDomain.PRICING_HISTORY].agent.tools
    }
    assert pricing_history_tool_names == {"get_pricing_history"}
