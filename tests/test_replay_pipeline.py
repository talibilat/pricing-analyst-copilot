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
    ResultSource,
    ScenarioName,
    Segment,
    WorkflowResult,
)
from pricing_copilot.replay.pipeline import run_replay_portfolio_workflow
from pricing_copilot.replay.store import ReplayArtifactMissingError, save_replay_artifact


def _question(scenario: ScenarioName | None) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=scenario,
    )


def _record(settings: Settings) -> None:
    question = _question(ScenarioName.CONTROLLED_INCREASE)
    result = WorkflowResult(
        question=question,
        specialist_reports=[],
        recommendation=Recommendation(
            action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
        ),
        governance_outcome=GovernanceOutcome(approved=True),
        missing_evidence=[],
    )
    response = ChatResponse(
        intent=ChatIntent.PRICING_ANALYSIS,
        context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
        message="increase",
        workflow_result=result,
    )
    save_replay_artifact(response, settings)


def test_run_replay_portfolio_workflow_returns_a_source_stamped_result(tmp_path: Path) -> None:
    settings = Settings(replay_directory=tmp_path / "replay")
    _record(settings)

    result = run_replay_portfolio_workflow(_question(ScenarioName.CONTROLLED_INCREASE), settings)

    assert result.source is ResultSource.REPLAY
    assert result.recommendation.action is RecommendationAction.INCREASE


def test_run_replay_portfolio_workflow_raises_when_nothing_is_recorded(tmp_path: Path) -> None:
    settings = Settings(replay_directory=tmp_path / "replay")
    with pytest.raises(ReplayArtifactMissingError):
        run_replay_portfolio_workflow(_question(ScenarioName.RETENTION_CONCERN), settings)


def test_run_replay_portfolio_workflow_returns_missing_evidence_for_no_scenario(
    tmp_path: Path,
) -> None:
    settings = Settings(replay_directory=tmp_path / "replay")
    result = run_replay_portfolio_workflow(_question(None), settings)
    assert result.missing_evidence
