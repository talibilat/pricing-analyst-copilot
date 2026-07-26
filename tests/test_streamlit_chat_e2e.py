from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pricing_copilot.chat.contracts import (
    AnalyticsSource,
    ChatToolName,
    ConversationDecision,
    ConversationMessage,
    ConversationRoute,
)
from pricing_copilot.config import get_azure_openai_settings, get_settings
from pricing_copilot.contracts import ScenarioName

_azure_settings = get_azure_openai_settings()
requires_azure_openai = pytest.mark.skipif(
    not (_azure_settings.api_key and _azure_settings.endpoint),
    reason="Azure OpenAI credentials are required for a live recommendation.",
)


def _prototype_plan(
    self: object,
    message: str,
    history: Sequence[ConversationMessage],
    available_tools: dict[str, str],
) -> ConversationDecision:
    lowered = message.lower()
    if "capital of france" in lowered:
        return ConversationDecision(
            route=ConversationRoute.DIRECT_ANSWER,
            response="Paris is the capital of France.",
        )
    if "what was our price" in lowered:
        return ConversationDecision(
            route=ConversationRoute.CLARIFY,
            clarification_question=(
                "When you say price, do you mean the last approved renewal action "
                "or the average quoted premium?"
            ),
            suggested_next_steps=[
                "Check the approved renewal action.",
                "Check the average quoted premium.",
            ],
        )
    if "average quoted premium" in lowered:
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.ANALYTICS,
            sources=[AnalyticsSource.CONVERSION],
            requested_fields=["period", "average_quoted_premium_gbp"],
        )
    if any(
        phrase in lowered for phrase in ("ignore prior instructions", "customer_id", "drop table")
    ):
        return ConversationDecision(
            route=ConversationRoute.REFUSE,
            response="I cannot bypass controls or execute destructive database operations.",
        )
    if lowered.lstrip().startswith(("select ", "with ")):
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.READ_ONLY_SQL,
            sql=message,
        )
    if "replay" in lowered:
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.REPLAY,
            scenario=(
                ScenarioName.RETENTION_CONCERN
                if "retention" in lowered
                else ScenarioName.CONTROLLED_INCREASE
            ),
        )
    if "evaluation" in lowered:
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.EVALUATION,
        )
    if "drift" in lowered:
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.DRIFT,
        )
    if "recommend" in lowered:
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.RECOMMENDATION,
        )
    if "market intelligence" in lowered:
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.DOCUMENTS,
            sources=[AnalyticsSource.MARKET_INTELLIGENCE],
        )
    sources = [
        source
        for phrase, source in (
            ("claims", AnalyticsSource.CLAIMS),
            ("conversion", AnalyticsSource.CONVERSION),
            ("competitor", AnalyticsSource.COMPETITORS),
            ("pricing", AnalyticsSource.PRICING_HISTORY),
        )
        if phrase in lowered
    ]
    return ConversationDecision(
        route=ConversationRoute.TOOL_CALL,
        tool_name=ChatToolName.ANALYTICS,
        sources=sources,
        scenario=(ScenarioName.RETENTION_CONCERN if "retention concern" in lowered else None),
    )


@pytest.fixture(autouse=True)
def configure_offline_conversation_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    get_settings.cache_clear()
    get_azure_openai_settings.cache_clear()
    monkeypatch.setattr(
        "pricing_copilot.chat.conversation_graph.AgentsSdkConversationPlanner.plan",
        _prototype_plan,
    )
    yield
    get_settings.cache_clear()
    get_azure_openai_settings.cache_clear()


def test_streamlit_answers_a_stable_fact_without_a_business_tool() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    app.chat_input[0].set_value("What is the capital of France?")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Paris is the capital of France" in markdown
    assert not app.dataframe


def test_streamlit_clarifies_price_and_uses_the_follow_up() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    app.chat_input[0].set_value("What was our price last month?")
    app.run()
    app.chat_input[0].set_value("Show the average quoted premium")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "last approved renewal action" in markdown
    assert not app.dataframe
    assert "## Direct answer" in markdown


def test_streamlit_clarification_suggestion_is_a_one_click_chat_action() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    app.chat_input[0].set_value("What was our price last month?")
    app.run()

    suggestion = next(
        button for button in app.button if button.label == "Check the average quoted premium."
    )
    suggestion.click()
    app.run()

    assert not app.exception
    assert any(
        message.name == "user" and "average quoted premium" in message.markdown[0].value.lower()
        for message in app.chat_message
    )
    assert app.dataframe
    assert not any(
        button.label in {"Check the approved renewal action.", "Check the average quoted premium."}
        for button in app.button
    )


def test_new_streamlit_session_starts_without_previous_history() -> None:
    first = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    first.run()
    first.chat_input[0].set_value("What is the capital of France?")
    first.run()
    assert len(first.chat_message) == 3

    refreshed = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    refreshed.run()

    assert len(refreshed.chat_message) == 1


def test_streamlit_chat_runs_a_safe_multi_source_query() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert len(app.chat_input) == 1
    app.chat_input[0].set_value("Show claims and conversion performance")
    app.run()

    assert not app.exception
    assert len(app.chat_message) == 3
    assert len(app.dataframe) == 0
    markdown = "\n".join(item.value for item in app.markdown)
    assert "## Direct answer" in markdown
    assert "## Key evidence" in markdown
    assert "loss ratio moved" in markdown.lower()


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


@requires_azure_openai
def test_recommendation_response_shows_confidence_and_fair_value() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Confidence" in markdown
    assert "Fair value" in markdown or "Fair-value" in markdown


@requires_azure_openai
def test_recommendation_response_shows_expandable_evidence_detail() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    assert app.expander
    expander_labels = [e.label for e in app.expander]
    assert any("Evidence detail" in label for label in expander_labels)


@requires_azure_openai
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


def test_claims_only_question_returns_an_interpreted_answer() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show claims performance")
    app.run()

    assert not app.exception
    assert len(app.dataframe) == 0
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Claims performance deteriorated" in markdown


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
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Direct answer" in markdown


def test_an_unsafe_request_is_refused_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("DROP TABLE claims")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "cannot bypass controls" in markdown.lower()


@requires_azure_openai
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
    assert len(app.dataframe) == 0
    markdown = "\n".join(item.value for item in app.markdown)
    assert "What would you like to review?" not in markdown
    assert "## Key evidence" in markdown


def test_current_chat_history_survives_multiple_message_reruns() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    app.chat_input[0].set_value("Hi hello")
    app.run()
    app.session_state["pending_chat_prompt"] = "What did competitors do this period?"
    app.run()

    assert not app.exception
    assert len(app.chat_message) == 5
    chat_text = "\n".join(message.markdown[0].value for message in app.chat_message[1::2])
    assert "Hi hello" in chat_text
    assert "What did competitors do this period?" in chat_text


def test_new_streamlit_session_starts_with_clean_chat_history() -> None:
    first_session = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    first_session.run()
    first_session.chat_input[0].set_value("Hi hello")
    first_session.run()
    assert len(first_session.chat_message) == 3

    refreshed_session = AppTest.from_file(
        "src/pricing_copilot/streamlit_app.py", default_timeout=10
    )
    refreshed_session.run()

    assert not refreshed_session.exception
    assert len(refreshed_session.chat_message) == 1


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
