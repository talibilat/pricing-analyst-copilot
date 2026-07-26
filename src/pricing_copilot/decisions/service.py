from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import AnalystDecision, DecisionRequest
from pricing_copilot.decisions.store import DecisionStore
from pricing_copilot.intelligence.store import IntelligenceCatalogue
from pricing_copilot.versions import current_configuration_versions


def record_analyst_decision(
    request: DecisionRequest, settings: Settings, store: DecisionStore
) -> AnalystDecision:
    configuration_versions = current_configuration_versions(settings)
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
        source=request.source,
    )
    store.save(decision)
    if decision.record_id is not None:
        IntelligenceCatalogue(
            settings.market_intelligence_database_path
        ).save_recommendation_outcome(
            decision.record_id,
            {
                "recommendation_action": request.recommendation.action.value,
                "confidence_score": (
                    request.recommendation.confidence.overall
                    if request.recommendation.confidence is not None
                    else None
                ),
                "human_review_result": request.decision.value,
                "business_outcome": "pending",
                "evidence_references": decision.evidence_ids,
                "model_and_prompt_versions": decision.configuration_versions.model_dump(
                    mode="json"
                ),
            },
        )
    return decision


@lru_cache
def get_decision_store() -> DecisionStore:
    settings = get_settings()
    return DecisionStore.from_path(Path(settings.decision_store_path))
