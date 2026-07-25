from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.data.generation import DEFAULT_SCENARIO_SEED, DEFAULT_SCENARIO_VERSION
from pricing_copilot.governance.registry import AGENT_REGISTRY_VERSION
from pricing_copilot.observability.trace import POLICY_VERSION, PROMPT_VERSION, TOOL_VERSION
from pricing_copilot.recommendation.governance import GOVERNANCE_VERSION

GOVERNED_RECOMMENDATION_VERSION = "governed-multi-agent-v1"


def current_configuration_versions(settings: Settings) -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name=settings.model_name,
        recommendation_version=GOVERNED_RECOMMENDATION_VERSION,
        governance_version=GOVERNANCE_VERSION,
        scenario_seed=DEFAULT_SCENARIO_SEED,
        scenario_version=DEFAULT_SCENARIO_VERSION,
        max_price_movement_pct=settings.policy.max_price_movement_pct,
        prompt_version=PROMPT_VERSION,
        agent_registry_version=AGENT_REGISTRY_VERSION,
        tool_version=TOOL_VERSION,
        dataset_version=DEFAULT_SCENARIO_VERSION,
        recommendation_policy_version=POLICY_VERSION,
    )
