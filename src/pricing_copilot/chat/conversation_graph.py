from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from time import monotonic
from typing import Protocol

from agents import Agent, OpenAIChatCompletionsModel, RunConfig, Runner
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from openai import AsyncOpenAI

from pricing_copilot.catalog import SUPPORTED_PORTFOLIOS
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
from pricing_copilot.chat.query_planning import plan_request
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
        available_tools: dict[str, object],
        context: ChatContext,
    ) -> ConversationDecision: ...


class ConversationToolExecutor(Protocol):
    def available_tools(self) -> dict[str, object]: ...

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
        available_tools: dict[str, object],
        context: ChatContext,
    ) -> ConversationDecision:
        azure = get_azure_openai_settings()
        if not azure.api_key or not azure.endpoint:
            raise PlannerUnavailableError(
                "The conversation model is not configured in this environment."
            )
        return asyncio.run(self._plan_and_close(message, history, available_tools, context))

    async def _plan_and_close(
        self,
        message: str,
        history: Sequence[ConversationMessage],
        available_tools: dict[str, object],
        context: ChatContext,
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
                "active_scope": context.model_dump(mode="json"),
                "supported_portfolios": [
                    {
                        "product": product.value,
                        "region": region.value,
                        "segment": segment.value,
                    }
                    for product, region, segment in sorted(SUPPORTED_PORTFOLIOS)
                ],
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
                    context,
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
        decision = self._recover_pending_request(decision, context)
        decision = plan_request(state.message, decision)
        decision = self._execute_scoped_recommendation(decision, context)
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
        if decision.route is ConversationRoute.CLARIFY:
            active_context = active_context.model_copy(
                update={
                    "pending_tool_name": decision.tool_name or context.pending_tool_name,
                    "pending_intent": decision.intent or context.pending_intent,
                }
            )
        else:
            active_context = active_context.model_copy(
                update={"pending_tool_name": None, "pending_intent": None}
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
    def _recover_pending_request(
        decision: ConversationDecision, context: ChatContext
    ) -> ConversationDecision:
        """Recover a terse suggestion reply when the model drops its prior tool choice.

        This deliberately applies only to the planner's empty analytics fallback.
        A new, explicit question remains free to take its own route.
        """
        if (
            context.pending_tool_name is None
            or decision.route is not ConversationRoute.TOOL_CALL
            or decision.tool_name is not ChatToolName.ANALYTICS
            or decision.sources
            or decision.requested_fields
        ):
            return decision
        return decision.model_copy(
            update={
                "tool_name": context.pending_tool_name,
                "intent": context.pending_intent,
            }
        )

    @staticmethod
    def _execute_scoped_recommendation(
        decision: ConversationDecision, context: ChatContext
    ) -> ConversationDecision:
        """Do not re-ask for a portfolio scope that the session already supplies."""
        if (
            decision.route is not ConversationRoute.CLARIFY
            or decision.tool_name is not ChatToolName.RECOMMENDATION
            or context.segment is None
        ):
            return decision
        return decision.model_copy(
            update={
                "route": ConversationRoute.TOOL_CALL,
                "clarification_question": None,
                "suggested_next_steps": [],
            }
        )

    @staticmethod
    def _plan_details(decision: ConversationDecision, context: ChatContext) -> list[str]:
        scope = " ".join(
            value.replace("_", " ").title()
            for value in (
                context.region.value,
                context.product.value,
                context.segment.value if context.segment else "portfolio",
            )
        )
        if decision.route is ConversationRoute.DIRECT_ANSWER:
            return ["Plan: answer directly. No data tools or agents are needed."]
        if decision.route is ConversationRoute.CLARIFY:
            return ["Plan: ask for the missing portfolio scope before calling any data tools."]
        if decision.route is ConversationRoute.REFUSE:
            return ["Plan: decline the request because it is outside the supported scope."]
        details = [f"Scope: {scope}."]
        plan = decision.structured_plan
        if plan is None:
            details.append("Next: call the selected tool and present its result.")
            return details
        details.append(f"Intent: {plan.intent.value.replace('_', ' ')}.")
        details.append(f"Question type: {plan.analysis_type.value.replace('_', ' ')}.")
        details.append("Evidence to combine:")
        details.extend(f"  - {question}" for question in plan.sub_questions)
        if plan.tool_calls:
            details.append("Required tool calls:")
            for tool_call in plan.tool_calls:
                supported = "; ".join(tool_call.supports_questions)
                details.append(
                    f"  - {tool_call.source.value.replace('_', ' ')}: "
                    f"{tool_call.reason} Supports: {supported}"
                )
        else:
            details.append("Required tool calls: none.")
        details.append(f"Required filters: {', '.join(plan.required_filters)}.")
        details.append(f"Final-answer sections: {', '.join(plan.answer_sections)}.")
        details.append(f"Evidence rule: {plan.evidence_rule}")
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
