from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from time import monotonic
from typing import Protocol

from agents import Agent, OpenAIChatCompletionsModel, RunConfig, Runner
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from openai import AsyncOpenAI

from pricing_copilot.chat.contracts import (
    ActivityStatus,
    ChatActivity,
    ChatContext,
    ChatIntent,
    ChatResponse,
    ChatToolName,
    ConversationDecision,
    ConversationMessage,
    ConversationRoute,
    ConversationState,
)
from pricing_copilot.chat.prompts import CONVERSATION_AGENT_PROMPT
from pricing_copilot.config import (
    Settings,
    azure_openai_base_url,
    get_azure_openai_settings,
)
from pricing_copilot.governance.registry import require_approved_agent

ActivityListener = Callable[[ChatActivity], None]


class ConversationPlanner(Protocol):
    def plan(
        self,
        message: str,
        history: Sequence[ConversationMessage],
        available_tools: dict[str, str],
    ) -> ConversationDecision: ...


class ConversationToolExecutor(Protocol):
    def available_tools(self) -> dict[str, str]: ...

    def execute(
        self,
        message: str,
        decision: ConversationDecision,
        context: ChatContext,
        listener: ActivityListener | None,
    ) -> ChatResponse: ...


class PlannerUnavailableError(RuntimeError):
    """Raised when the configured conversation model cannot be used."""


class AgentsSdkConversationPlanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def plan(
        self,
        message: str,
        history: Sequence[ConversationMessage],
        available_tools: dict[str, str],
    ) -> ConversationDecision:
        azure = get_azure_openai_settings()
        if not azure.api_key or not azure.endpoint:
            raise PlannerUnavailableError(
                "The conversation model is not configured in this environment."
            )
        return asyncio.run(self._plan_and_close(message, history, available_tools))

    async def _plan_and_close(
        self,
        message: str,
        history: Sequence[ConversationMessage],
        available_tools: dict[str, str],
    ) -> ConversationDecision:
        azure = get_azure_openai_settings()
        if not azure.api_key or not azure.endpoint:
            raise PlannerUnavailableError(
                "The conversation model is not configured in this environment."
            )
        client = AsyncOpenAI(
            api_key=azure.api_key,
            base_url=azure_openai_base_url(azure.endpoint),
        )
        model = OpenAIChatCompletionsModel(
            model=azure.chat_deployment or self.settings.model_name,
            openai_client=client,
        )
        agent = Agent(
            name="conversation-agent",
            instructions=CONVERSATION_AGENT_PROMPT,
            tools=[],
            output_type=ConversationDecision,
            model=model,
        )
        require_approved_agent(
            "conversation-agent",
            tool_names=set(),
            output_contract="ConversationDecision",
        )
        prompt = json.dumps(
            {
                "current_message": message,
                "session_history": [item.model_dump(mode="json") for item in history[-20:]],
                "available_tools": available_tools,
            },
            ensure_ascii=False,
        )
        retryable = (TimeoutError, MaxTurnsExceeded, ModelBehaviorError)
        try:
            for attempt in range(self.settings.max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        Runner.run(
                            agent,
                            prompt,
                            max_turns=self.settings.max_agent_turns,
                            run_config=RunConfig(
                                tracing_disabled=not self.settings.agents_sdk_tracing_enabled,
                                trace_include_sensitive_data=False,
                            ),
                        ),
                        timeout=self.settings.request_timeout_seconds,
                    )
                except retryable:
                    if attempt >= self.settings.max_retries:
                        raise
                    continue
                output = result.final_output
                if isinstance(output, ConversationDecision):
                    return output
                return ConversationDecision.model_validate(output)
        finally:
            await client.close()
        raise AssertionError(
            "Conversation planner exhausted attempts without returning or raising."
        )


class ConversationGraph:
    def __init__(
        self,
        planner: ConversationPlanner,
        tools: ConversationToolExecutor,
    ) -> None:
        self.planner = planner
        self.tools = tools

    def run(
        self,
        message: str,
        context: ChatContext,
        *,
        history: Sequence[ConversationMessage] = (),
        on_activity: ActivityListener | None = None,
    ) -> ChatResponse:
        state = ConversationState(
            message=" ".join(message.split()),
            history=list(history),
            context=context,
        )
        planning_activities: list[ChatActivity] = []

        def report_planning(activity: ChatActivity) -> None:
            planning_activities.append(activity)
            if on_activity is not None:
                on_activity(activity)

        if context.force_replay:
            decision = ConversationDecision(
                route=ConversationRoute.TOOL_CALL,
                tool_name=ChatToolName.REPLAY,
                scenario=context.scenario,
            )
        else:
            planning_started = monotonic()
            report_planning(
                ChatActivity(
                    status=ActivityStatus.WORKING,
                    label="Conversation planning",
                    purpose="Interpreting the request and selecting the right tools.",
                    agent="conversation-agent",
                )
            )
            try:
                decision = self.planner.plan(
                    state.message,
                    state.history,
                    self.tools.available_tools(),
                )
            except Exception as exc:
                report_planning(
                    ChatActivity(
                        status=ActivityStatus.FAILED,
                        label="Conversation planning",
                        purpose="The request could not be interpreted.",
                        agent="conversation-agent",
                        duration_ms=(monotonic() - planning_started) * 1_000,
                    )
                )
                return ChatResponse(
                    intent=ChatIntent.HELP,
                    route=ConversationRoute.CLARIFY,
                    context=context,
                    message=(
                        "I cannot interpret that request with the conversation model right now. "
                        "I have not called any business tool or guessed an answer."
                    ),
                    limitations=[f"Conversation planning is unavailable: {type(exc).__name__}."],
                    suggested_next_steps=[
                        "Check the Azure OpenAI configuration and try again.",
                        "Use a recorded replay if you need a previously validated recommendation.",
                    ],
                    requires_clarification=True,
                    activities=planning_activities,
                    plan_details=[
                        "Decision: ask for clarification because the request could not be planned."
                    ],
                )
            report_planning(
                ChatActivity(
                    status=ActivityStatus.COMPLETED,
                    label="Conversation planning",
                    purpose="Created a plan and selected the required tools.",
                    agent="conversation-agent",
                    duration_ms=(monotonic() - planning_started) * 1_000,
                )
            )
        state = state.model_copy(update={"decision": decision})
        active_context = context.model_copy(
            update={
                "scenario": decision.scenario or context.scenario,
                "product": decision.product or context.product,
                "region": decision.region or context.region,
                "segment": decision.segment or context.segment,
                "analysis_start_month": decision.start_month or context.analysis_start_month,
                "analysis_end_month": decision.end_month or context.analysis_end_month,
            }
        )
        if decision.route is ConversationRoute.DIRECT_ANSWER:
            response = self._compose_without_tool(
                ChatIntent.GENERAL_ANSWER,
                decision.response or "",
                decision,
                active_context,
            )
            return response.model_copy(
                update={
                    "activities": planning_activities,
                    "plan_details": self._plan_details(decision, active_context),
                }
            )
        if decision.route is ConversationRoute.CLARIFY:
            question = decision.clarification_question or "Could you clarify what you mean?"
            response = self._compose_without_tool(
                ChatIntent.CLARIFICATION,
                question,
                decision,
                active_context,
                requires_clarification=True,
            )
            return response.model_copy(
                update={
                    "activities": planning_activities,
                    "plan_details": self._plan_details(decision, active_context),
                }
            )
        if decision.route is ConversationRoute.REFUSE:
            response = self._compose_without_tool(
                ChatIntent.UNSUPPORTED,
                decision.response or "I cannot help with that request.",
                decision,
                active_context,
                refused=True,
            )
            return response.model_copy(
                update={
                    "activities": planning_activities,
                    "plan_details": self._plan_details(decision, active_context),
                }
            )
        response = self.tools.execute(state.message, decision, active_context, on_activity)
        return response.model_copy(
            update={
                "route": ConversationRoute.TOOL_CALL,
                "activities": [*planning_activities, *response.activities],
                "plan_details": self._plan_details(decision, active_context),
                "limitations": [*response.limitations, *decision.limitations],
                "suggested_next_steps": [
                    *response.suggested_next_steps,
                    *decision.suggested_next_steps,
                ][:3],
            }
        )

    @staticmethod
    def _plan_details(
        decision: ConversationDecision, context: ChatContext
    ) -> list[str]:
        tool_labels = {
            ChatToolName.ANALYTICS: "retrieve portfolio data",
            ChatToolName.SCHEMA: "review the available data tables",
            ChatToolName.DOCUMENTS: "retrieve market or customer-feedback evidence",
            ChatToolName.REPLAY: "load a recorded analysis",
            ChatToolName.EVALUATION: "review the latest evaluation report",
            ChatToolName.DRIFT: "review the latest monitoring report",
            ChatToolName.RECOMMENDATION: "run the portfolio analysis workflow",
            ChatToolName.READ_ONLY_SQL: "run a validated read-only query",
        }
        scope = " ".join(
            value.replace("_", " ")
            for value in (
                context.region.value,
                context.product.value,
                context.segment.value if context.segment else "portfolio",
            )
        )
        if decision.route is ConversationRoute.DIRECT_ANSWER:
            return ["Decision: answer directly. No data tools were needed."]
        if decision.route is ConversationRoute.CLARIFY:
            return ["Decision: ask for the missing portfolio scope before retrieving data."]
        if decision.route is ConversationRoute.REFUSE:
            return ["Decision: decline the request because it is outside the supported scope."]
        details = [
            f"Decision: {tool_labels.get(decision.tool_name, 'complete the requested task')}.",
            f"Scope: {scope}.",
        ]
        if decision.sources:
            sources = ", ".join(source.value.replace("_", " ") for source in decision.sources)
            details.append(f"Planned data sources: {sources}.")
        elif decision.tool_name is ChatToolName.RECOMMENDATION:
            details.append(
                "Planned evidence: claims, conversion, competitors, pricing history, market "
                "intelligence, and customer feedback."
            )
        return details

    @staticmethod
    def _compose_without_tool(
        intent: ChatIntent,
        message: str,
        decision: ConversationDecision,
        context: ChatContext,
        *,
        requires_clarification: bool = False,
        refused: bool = False,
    ) -> ChatResponse:
        return ChatResponse(
            intent=intent,
            route=decision.route,
            context=context,
            message=message,
            clarification_question=decision.clarification_question,
            limitations=decision.limitations,
            suggested_next_steps=decision.suggested_next_steps,
            requires_clarification=requires_clarification,
            refused=refused,
        )
