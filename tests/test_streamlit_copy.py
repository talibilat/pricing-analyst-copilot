from pathlib import Path

BANNED_PHRASES = [
    "price updated",
    "price has been updated",
    "price change executed",
    "pricing action executed",
]

SOURCE = Path("src/pricing_copilot/streamlit_app.py").read_text().lower()


def test_streamlit_app_never_claims_a_price_was_executed() -> None:
    for phrase in BANNED_PHRASES:
        assert phrase not in SOURCE, f"Found banned phrase: {phrase!r}"


def test_streamlit_app_distinguishes_recommendation_from_decision() -> None:
    assert "supporting evidence" in SOURCE
    assert "analyst decision" in SOURCE or "analyst review" in SOURCE


def test_streamlit_app_distinguishes_policy_review_from_regulatory_compliance() -> None:
    assert "does not execute a pricing change" in SOURCE


def test_streamlit_app_is_chat_first_with_activity_feedback() -> None:
    assert "st.chat_message" in SOURCE
    assert "st.chat_input" in SOURCE
    assert "plan, decisions, and tool calls" in SOURCE
    assert "completed in" in SOURCE
    assert "activity.status is activitystatus.working" in SOURCE


def test_streamlit_chat_layout_uses_a_native_fixed_composer_and_separates_roles() -> None:
    assert "st.bottom" in SOURCE
    assert "st.chat_message(\"user\")" in SOURCE
    assert "st.chat_message(\"assistant\"" in SOURCE
    assert "assistant_avatar_data_uri" in SOURCE


def test_streamlit_clarification_recommendations_are_buttons() -> None:
    assert "response.requires_clarification" in SOURCE
    assert "pending_chat_prompt" in SOURCE
    assert 'key=f"chat_suggestion_' in SOURCE
