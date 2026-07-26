from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

AGENT_REGISTRY_VERSION = "approved-agent-registry-v1"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentRegistration(BaseModel):
    name: str
    owner: str
    version: str
    risk_tier: RiskTier
    permitted_tools: tuple[str, ...]
    output_contract: str
    evaluation_suite: str


APPROVED_AGENT_REGISTRY: dict[str, AgentRegistration] = {
    "chat-orchestrator": AgentRegistration(
        name="chat-orchestrator",
        owner="Pricing Decision Copilot",
        version="v1",
        risk_tier=RiskTier.HIGH,
        permitted_tools=(),
        output_contract="ChatOrchestrationPlan",
        evaluation_suite="tests/test_chat_orchestrator.py",
    ),
    "portfolio-supervisor": AgentRegistration(
        name="portfolio-supervisor",
        owner="Pricing Decision Copilot",
        version="v1",
        risk_tier=RiskTier.HIGH,
        permitted_tools=(),
        output_contract="WorkflowResult",
        evaluation_suite="tests/test_orchestration_supervisor.py",
    ),
    "claims-specialist": AgentRegistration(
        name="claims-specialist",
        owner="Claims Analytics",
        version="v1",
        risk_tier=RiskTier.MEDIUM,
        permitted_tools=("get_claims_metrics",),
        output_contract="SpecialistFindings",
        evaluation_suite="tests/test_orchestration_specialists.py",
    ),
    "conversion-specialist": AgentRegistration(
        name="conversion-specialist",
        owner="Customer Analytics",
        version="v1",
        risk_tier=RiskTier.MEDIUM,
        permitted_tools=("get_conversion_metrics",),
        output_contract="SpecialistFindings",
        evaluation_suite="tests/test_orchestration_specialists.py",
    ),
    "market-intelligence-specialist": AgentRegistration(
        name="market-intelligence-specialist",
        owner="Market Intelligence",
        version="v1",
        risk_tier=RiskTier.HIGH,
        permitted_tools=("get_competitor_metrics", "get_market_intelligence_documents"),
        output_contract="SpecialistFindings",
        evaluation_suite="tests/test_security_controls.py",
    ),
    "pricing-history-specialist": AgentRegistration(
        name="pricing-history-specialist",
        owner="Pricing Governance",
        version="v1",
        risk_tier=RiskTier.MEDIUM,
        permitted_tools=("get_pricing_history",),
        output_contract="SpecialistFindings",
        evaluation_suite="tests/test_orchestration_specialists.py",
    ),
    "recommendation-agent": AgentRegistration(
        name="recommendation-agent",
        owner="Pricing Decision Copilot",
        version="v1",
        risk_tier=RiskTier.HIGH,
        permitted_tools=(),
        output_contract="RecommendationDraft",
        evaluation_suite="tests/test_orchestration_recommendation_agent.py",
    ),
    "governance-agent": AgentRegistration(
        name="governance-agent",
        owner="Model Risk and Governance",
        version="v1",
        risk_tier=RiskTier.HIGH,
        permitted_tools=(),
        output_contract="GovernanceReview",
        evaluation_suite="tests/test_orchestration_governance_agent.py",
    ),
}


class UnapprovedAgentError(ValueError):
    """Raised when runtime code attempts to use an unregistered agent or capability."""


def require_approved_agent(
    name: str, *, tool_names: set[str], output_contract: str
) -> AgentRegistration:
    registration = APPROVED_AGENT_REGISTRY.get(name)
    if registration is None:
        raise UnapprovedAgentError(
            f"Agent {name!r} is not in registry {AGENT_REGISTRY_VERSION}; runtime agent "
            "creation is prohibited."
        )
    if tool_names != set(registration.permitted_tools):
        raise UnapprovedAgentError(
            f"Agent {name!r} requested tools {sorted(tool_names)}, but its registry permits "
            f"{sorted(registration.permitted_tools)}."
        )
    if output_contract != registration.output_contract:
        raise UnapprovedAgentError(
            f"Agent {name!r} requested output contract {output_contract!r}, but its registry "
            f"requires {registration.output_contract!r}."
        )
    return registration


def registry_snapshot() -> list[AgentRegistration]:
    return list(APPROVED_AGENT_REGISTRY.values())
