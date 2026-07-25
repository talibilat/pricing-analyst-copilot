from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_streamlit_chat_runs_a_safe_multi_source_query() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert len(app.chat_input) == 1
    app.chat_input[0].set_value("Show claims and conversion performance")
    app.run()

    assert not app.exception
    assert len(app.chat_message) == 3
    assert len(app.dataframe) == 2
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Getting information from claims performance data" in markdown
    assert "Getting information from conversion performance data" in markdown


def test_replay_keyword_shows_a_prominent_replay_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

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
    from pricing_copilot.replay.store import save_replay_artifact

    replay_dir = tmp_path / "replay"
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(replay_dir))
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question,
                specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True),
                missing_evidence=[],
            ),
        ),
        Settings(replay_directory=replay_dir),
    )

    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Replay the controlled increase scenario")
    app.run()

    assert not app.exception
    warnings = "\n".join(w.body for w in app.warning)
    assert "REPLAY MODE" in warnings


def test_replay_of_an_unrecorded_scenario_fails_gracefully_in_the_interface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(tmp_path / "replay"))

    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Replay the retention concern scenario")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "not available" in markdown.lower() or "not" in markdown.lower()


def test_recommendation_response_shows_confidence_and_fair_value() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Confidence" in markdown
    assert "Fair value" in markdown or "Fair-value" in markdown


def test_monitoring_tab_shows_an_honest_message_with_no_drift_report_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pricing_copilot.config import get_settings

    monkeypatch.setenv("PRICING_COPILOT_DRIFT_DIRECTORY", str(tmp_path / "drift"))
    get_settings.cache_clear()
    try:
        app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
        app.run()

        assert not app.exception
        assert app.tabs
        info_messages = "\n".join(block.value for block in app.info)
        assert "no drift monitoring run" in info_messages.lower()
    finally:
        get_settings.cache_clear()
