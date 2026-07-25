from __future__ import annotations

from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import PortfolioQuestion, ResultSource, WorkflowResult
from pricing_copilot.replay.store import load_replay_artifact
from pricing_copilot.workflow_common import (
    IMPLEMENTED_DATA_SCENARIOS,
    missing_evidence_workflow_result,
)


def run_replay_portfolio_workflow(
    question: PortfolioQuestion, settings: Settings | None = None
) -> WorkflowResult:
    settings = settings or get_settings()
    if question.scenario not in IMPLEMENTED_DATA_SCENARIOS:
        return missing_evidence_workflow_result(question)
    artifact = load_replay_artifact(question.scenario, settings)
    result = artifact.chat_response.workflow_result
    if result is None:  # pragma: no cover - save_replay_artifact never persists a null result
        raise ValueError(f"Replay artifact for {question.scenario.value} has no workflow_result.")
    return result.model_copy(update={"source": ResultSource.REPLAY})
