from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import AnalystDecision, ConfigurationVersions, DecisionRequest
from pricing_copilot.data.generation import DEFAULT_SCENARIO_SEED, DEFAULT_SCENARIO_VERSION
from pricing_copilot.decisions.store import DecisionStore
from pricing_copilot.governance.registry import AGENT_REGISTRY_VERSION
from pricing_copilot.observability.trace import POLICY_VERSION, PROMPT_VERSION, TOOL_VERSION
from pricing_copilot.orchestration.pipeline import GOVERNED_RECOMMENDATION_VERSION
from pricing_copilot.recommendation.governance import GOVERNANCE_VERSION


def record_analyst_decision(
    request: DecisionRequest, settings: Settings, store: DecisionStore
) -> AnalystDecision:
    configuration_versions = ConfigurationVersions(
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
    decision = AnalystDecision(
        record_id=str(uuid.uuid4()),
        question=request.question,
        recommendation=request.recommendation,
        governance_outcome=request.governance_outcome,
        evidence_ids=request.recommendation.cited_evidence_ids,
        decision=request.decision,
        rationale=request.rationale,
        conditions=request.conditions,
        decided_at=datetime.now(UTC),
        configuration_versions=configuration_versions,
    )
    store.save(decision)
    return decision


@lru_cache
def get_decision_store() -> DecisionStore:
    settings = get_settings()
    return DecisionStore.from_path(Path(settings.decision_store_path))
