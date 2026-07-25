from datetime import date
from pathlib import Path

import pytest

from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
    WorkflowResult,
)
from pricing_copilot.replay.store import (
    ReplayArtifactIncompatibleError,
    ReplayArtifactMissingError,
    load_replay_artifact,
    save_replay_artifact,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(replay_directory=tmp_path / "replay")


def _workflow_result() -> WorkflowResult:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    return WorkflowResult(
        question=question,
        specialist_reports=[],
        recommendation=Recommendation(
            action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
        ),
        governance_outcome=GovernanceOutcome(approved=True),
        missing_evidence=[],
    )


def _chat_response() -> ChatResponse:
    return ChatResponse(
        intent=ChatIntent.PRICING_ANALYSIS,
        context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
        message="The governed workflow recommends increase.",
        workflow_result=_workflow_result(),
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    saved = save_replay_artifact(_chat_response(), settings)
    assert saved.scenario is ScenarioName.CONTROLLED_INCREASE

    loaded = load_replay_artifact(ScenarioName.CONTROLLED_INCREASE, settings)
    assert loaded.chat_response.workflow_result is not None
    assert (
        loaded.chat_response.workflow_result.recommendation.action
        is RecommendationAction.INCREASE
    )


def test_load_missing_artifact_raises_missing_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ReplayArtifactMissingError):
        load_replay_artifact(ScenarioName.RETENTION_CONCERN, settings)


def test_load_rejects_an_artifact_with_a_stale_configuration_version(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_replay_artifact(_chat_response(), settings)
    path = settings.replay_directory / f"{ScenarioName.CONTROLLED_INCREASE.value}.json"
    stale = path.read_text().replace(
        '"governance_version": "deterministic-governance-v1"',
        '"governance_version": "deterministic-governance-v0-stale"',
    )
    assert stale != path.read_text()
    path.write_text(stale)

    with pytest.raises(ReplayArtifactIncompatibleError, match="governance_version"):
        load_replay_artifact(ScenarioName.CONTROLLED_INCREASE, settings)
