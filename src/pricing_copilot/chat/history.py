"""Bounded conversation-history helpers for the chat UI and service."""

from __future__ import annotations

from typing import Literal

from pricing_copilot.chat.contracts import ConversationMessage

_HISTORY_LIMIT = 4_000
_TRUNCATION_NOTICE = "\n\n[Earlier response truncated for conversation context.]"


def conversation_history_message(
    role: Literal["user", "assistant"], content: str
) -> ConversationMessage:
    """Create a valid planner-history message without changing the displayed reply.

    The chat transcript can contain a detailed, analyst-facing response that is
    longer than the planner's 4,000-character history contract.
    Keep the beginning of that reply, which contains the direct answer and
    evidence summary, and mark the loss of detail explicitly for the next turn.
    """
    if len(content) > _HISTORY_LIMIT:
        content = content[: _HISTORY_LIMIT - len(_TRUNCATION_NOTICE)].rstrip() + _TRUNCATION_NOTICE
    return ConversationMessage(role=role, content=content)
