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


def test_recommendation_response_shows_expandable_evidence_detail() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    assert app.expander
    expander_labels = [e.label for e in app.expander]
    assert any("Evidence detail" in label for label in expander_labels)


def test_supporting_charts_include_severity_and_competitor_movement() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    captions = "\n".join(item.value for item in app.caption)
    assert "Claim severity" in captions
    assert "Competitor" in captions


def test_counter_evidence_uses_a_prominent_warning_block() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Replay the controlled increase scenario")
    app.run()

    assert not app.exception
    warning_bodies = "\n".join(w.body for w in app.warning)
    assert "Counter-evidence" in warning_bodies


def test_claims_only_query_returns_a_single_table() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show claims performance")
    app.run()

    assert not app.exception
    assert len(app.dataframe) == 1
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Getting information from claims performance data" in markdown


def test_evaluation_question_renders_the_targets_vs_actuals_table_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show me the evaluation results")
    app.run()

    assert not app.exception
    assert app.dataframe


def test_drift_question_renders_the_material_alert_table_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show me drift monitoring")
    app.run()

    assert not app.exception
    assert app.dataframe


def test_retention_concern_scenario_is_reachable_by_keyword() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("What did competitors do in the retention concern scenario?")
    app.run()

    assert not app.exception
    assert app.dataframe


def test_an_unsafe_request_is_refused_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("SELECT * FROM claims")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "cannot accept raw sql" in markdown.lower()


def test_analyst_can_record_an_approval_decision_from_the_chat_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    assert app.text_area
    app.text_area[0].set_value("Approving based on the evidence reviewed.")
    assert app.checkbox
    app.checkbox[-1].set_value(True)
    app.run()

    submit_buttons = [b for b in app.button if "Record analyst decision" in b.label]
    assert submit_buttons
    submit_buttons[0].click()
    app.run()

    assert not app.exception
    assert app.success


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


def test_streamlit_app_has_no_sidebar_content() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    assert not app.exception
    assert len(app.sidebar) == 0


def test_empty_state_shows_suggestion_chips_before_first_exchange() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert len(app.button) == 3
    assert any("recommend a pricing action" in b.label for b in app.button)


def test_clicking_a_suggestion_chip_runs_the_same_exchange_as_typing() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    claims_button = next(b for b in app.button if "claims and conversion" in b.label)
    claims_button.click().run()

    assert not app.exception
    assert len(app.chat_message) == 3
    assert len(app.dataframe) == 2


def test_replayed_workflow_result_renders_the_proposed_action_badge_and_confidence_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
    from pricing_copilot.config import Settings, get_settings
    from pricing_copilot.contracts import (
        AnalysisPeriod,
        GovernanceOutcome,
        PortfolioQuestion,
        PriceRange,
        Product,
        Recommendation,
        RecommendationAction,
        Region,
        ScenarioName,
        Segment,
        WorkflowResult,
    )
    from pricing_copilot.evidence.models import ConfidenceBreakdown
    from pricing_copilot.replay.store import save_replay_artifact

    replay_dir = tmp_path / "replay"
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(replay_dir))
    get_settings.cache_clear()
    try:
        question = PortfolioQuestion(
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            analysis_period=AnalysisPeriod(
                start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)
            ),
            scenario=ScenarioName.CONTROLLED_INCREASE,
        )
        save_replay_artifact(
            ChatResponse(
                intent=ChatIntent.PRICING_ANALYSIS,
                context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
                message="Recommends a controlled increase.",
                workflow_result=WorkflowResult(
                    question=question,
                    specialist_reports=[],
                    recommendation=Recommendation(
                        action=RecommendationAction.INCREASE,
                        price_range=PriceRange(lower_pct=2, upper_pct=3),
                        rationale="Loss ratio rose.",
                        confidence=ConfidenceBreakdown(
                            evidence_coverage=0.88,
                            source_freshness=0.91,
                            specialist_agreement=0.85,
                            data_quality=0.94,
                            conflict_penalty=0.08,
                            overall=0.9,
                        ),
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
        markdown_html = "\n".join(item.value for item in app.markdown)
        assert "Proposed: increase" in markdown_html
        assert "pc-conf-grid" in markdown_html
        assert "Evidence coverage" in markdown_html
    finally:
        get_settings.cache_clear()
