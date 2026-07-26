from collections.abc import Sequence

from pricing_copilot.chat.contracts import (
    ActivityStatus,
    ChatContext,
    ChatIntent,
    ChatResponse,
    ChatToolName,
    ConversationDecision,
    ConversationMessage,
    ConversationRoute,
)
from pricing_copilot.chat.conversation_graph import ConversationGraph


class RecordingPlanner:
    def __init__(self, decision: ConversationDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[str, list[ConversationMessage], dict[str, str]]] = []

    def plan(
        self,
        message: str,
        history: Sequence[ConversationMessage],
        available_tools: dict[str, str],
    ) -> ConversationDecision:
        self.calls.append((message, list(history), available_tools))
        return self.decision


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ConversationDecision, ChatContext]] = []

    def available_tools(self) -> dict[str, str]:
        return {"analytics": "Retrieve portfolio analytics."}

    def execute(
        self,
        message: str,
        decision: ConversationDecision,
        context: ChatContext,
        listener: object,
    ) -> ChatResponse:
        self.calls.append((message, decision, context))
        return ChatResponse(
            intent=ChatIntent.DATA_RETRIEVAL,
            message="Retrieved data.",
            context=context,
        )


def test_stable_fact_is_answered_without_a_business_tool() -> None:
    planner = RecordingPlanner(
        ConversationDecision(
            route=ConversationRoute.DIRECT_ANSWER,
            response="Paris is the capital of France.",
        )
    )
    tools = RecordingTools()

    response = ConversationGraph(planner, tools).run(
        "What is the capital of France?",
        ChatContext(),
    )

    assert response.intent is ChatIntent.GENERAL_ANSWER
    assert response.message == "Paris is the capital of France."
    assert response.plan_details == ["Decision: answer directly. No data tools were needed."]
    assert not tools.calls


def test_conversation_planning_reports_thinking_then_a_timed_plan() -> None:
    planner = RecordingPlanner(
        ConversationDecision(
            route=ConversationRoute.DIRECT_ANSWER,
            response="Paris is the capital of France.",
        )
    )
    activities = []

    response = ConversationGraph(planner, RecordingTools()).run(
        "What is the capital of France?",
        ChatContext(),
        on_activity=activities.append,
    )

    assert [activity.status for activity in activities] == [
        ActivityStatus.WORKING,
        ActivityStatus.COMPLETED,
    ]
    assert response.activities == activities
    assert activities[-1].duration_ms is not None


def test_ambiguity_uses_history_and_returns_a_personalized_question() -> None:
    planner = RecordingPlanner(
        ConversationDecision(
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
    )
    history = [
        ConversationMessage(
            role="user",
            content="I am reviewing the renewal portfolio.",
        )
    ]

    response = ConversationGraph(planner, RecordingTools()).run(
        "What was our price last month?",
        ChatContext(),
        history=history,
    )

    assert response.requires_clarification
    assert "approved renewal action" in response.message
    assert planner.calls[0][1] == history
    assert len(response.suggested_next_steps) == 2


def test_business_request_invokes_only_the_selected_tool() -> None:
    planner = RecordingPlanner(
        ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.ANALYTICS,
        )
    )
    tools = RecordingTools()

    response = ConversationGraph(planner, tools).run(
        "Show last month's premium.",
        ChatContext(),
    )

    assert response.intent is ChatIntent.DATA_RETRIEVAL
    assert len(tools.calls) == 1
    assert tools.calls[0][1].tool_name is ChatToolName.ANALYTICS


def test_force_replay_bypasses_the_planner() -> None:
    planner = RecordingPlanner(
        ConversationDecision(
            route=ConversationRoute.DIRECT_ANSWER,
            response="This must not be used.",
        )
    )
    tools = RecordingTools()

    ConversationGraph(planner, tools).run(
        "Try again.",
        ChatContext(force_replay=True),
    )

    assert not planner.calls
    assert tools.calls[0][1].tool_name is ChatToolName.REPLAY


def test_planner_failure_is_honest_and_does_not_call_a_tool() -> None:
    class FailingPlanner:
        def plan(
            self,
            message: str,
            history: Sequence[ConversationMessage],
            available_tools: dict[str, str],
        ) -> ConversationDecision:
            raise RuntimeError("model unavailable")

    tools = RecordingTools()

    response = ConversationGraph(FailingPlanner(), tools).run("Help me", ChatContext())

    assert response.requires_clarification
    assert "have not called any business tool" in response.message
    assert response.limitations
    assert not tools.calls
