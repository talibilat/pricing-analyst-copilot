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
    assert "system recommendation" in SOURCE
    assert "analyst decision" in SOURCE or "analyst review" in SOURCE


def test_streamlit_app_distinguishes_policy_review_from_regulatory_compliance() -> None:
    assert "policy-approved for qualified analyst review" in SOURCE
    assert "not a claim of regulatory compliance" in SOURCE


def test_streamlit_app_is_chat_first_with_activity_feedback() -> None:
    assert "st.chat_message" in SOURCE
    assert "st.chat_input" in SOURCE
    assert "st.spinner" in SOURCE
    assert "activity trace" in SOURCE


def test_streamlit_chat_layout_keeps_composer_fixed_and_separates_roles() -> None:
    assert "position: fixed" in SOURCE
    assert 'key="chat_history"' in SOURCE
    assert "autoscroll=true" in SOURCE
    assert "stchatmessageavataruser" in SOURCE
    assert "margin-left: auto" in SOURCE
    assert "stchatmessageavatarassistant" in SOURCE
    assert "margin-right: auto" in SOURCE
