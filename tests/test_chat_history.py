from pricing_copilot.chat.history import conversation_history_message


def test_long_assistant_response_is_bounded_for_conversation_history() -> None:
    message = conversation_history_message("assistant", "a" * 4_250)

    assert len(message.content) == 4_000
    assert message.content.endswith("[Earlier response truncated for conversation context.]")


def test_short_response_is_preserved_for_conversation_history() -> None:
    message = conversation_history_message("user", "Show the latest claims evidence.")

    assert message.content == "Show the latest claims evidence."
