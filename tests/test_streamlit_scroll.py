from pricing_copilot.streamlit_scroll import AUTO_SCROLL_SCRIPT


def test_auto_scroll_targets_the_streamlit_main_container_and_latest_message() -> None:
    assert '[data-testid="stMain"]' in AUTO_SCROLL_SCRIPT
    assert '[data-testid="stChatMessage"]' in AUTO_SCROLL_SCRIPT
    assert "scrollIntoView" in AUTO_SCROLL_SCRIPT
