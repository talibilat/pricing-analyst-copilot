import pytest

from pricing_copilot.governance.registry import (
    AGENT_REGISTRY_VERSION,
    APPROVED_AGENT_REGISTRY,
    UnapprovedAgentError,
    require_approved_agent,
)


def test_registry_records_owner_risk_tools_contract_and_evaluation_suite() -> None:
    assert AGENT_REGISTRY_VERSION
    assert len(APPROVED_AGENT_REGISTRY) == 8
    for registration in APPROVED_AGENT_REGISTRY.values():
        assert registration.owner
        assert registration.version
        assert registration.risk_tier
        assert registration.output_contract
        assert registration.evaluation_suite.startswith("tests/")


def test_registry_accepts_only_the_exact_permitted_capabilities() -> None:
    registration = require_approved_agent(
        "claims-specialist",
        tool_names={"get_claims_metrics"},
        output_contract="SpecialistFindings",
    )
    assert registration.name == "claims-specialist"


def test_runtime_agent_creation_is_rejected() -> None:
    with pytest.raises(UnapprovedAgentError, match="runtime agent creation is prohibited"):
        require_approved_agent(
            "dynamically-created-agent",
            tool_names=set(),
            output_contract="SpecialistFindings",
        )


def test_registered_agent_cannot_escalate_its_tools() -> None:
    with pytest.raises(UnapprovedAgentError, match="registry permits"):
        require_approved_agent(
            "claims-specialist",
            tool_names={"get_claims_metrics", "write_database"},
            output_contract="SpecialistFindings",
        )
