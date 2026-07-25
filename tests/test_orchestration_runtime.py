import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent, OpenAIChatCompletionsModel
from agents.exceptions import ModelBehaviorError

from pricing_copilot.config import Settings
from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.observability.contracts import TraceEventKind
from pricing_copilot.observability.trace import WorkflowTraceRecorder
from pricing_copilot.orchestration.contracts import GovernanceReview
from pricing_copilot.orchestration.runtime import (
    AgentRuntime,
    BoundedRunHooks,
    RuntimeLimitExceeded,
)
from pricing_copilot.recommendation.contracts import RecommendationDraft


def _recorder(settings: Settings) -> WorkflowTraceRecorder:
    return WorkflowTraceRecorder(
        settings,
        {
            "policy_version": "v1",
            "agent_registry_version": "v1",
        },
    )


def test_runtime_retries_a_failed_model_operation_at_most_once(
    monkeypatch: pytest.MonkeyPatch,
    azure_chat_model: OpenAIChatCompletionsModel,
) -> None:
    settings = Settings(local_tracing_enabled=False, max_retries=1)
    recorder = _recorder(settings)
    runtime = AgentRuntime(settings, recorder)
    agent = Agent(
        name="recommendation-agent",
        instructions="Return a hold.",
        tools=[],
        output_type=RecommendationDraft,
        model=azure_chat_model,
    )
    calls = 0
    seen_max_turns: list[int | None] = []

    async def _run(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        seen_max_turns.append(kwargs.get("max_turns"))
        if calls == 1:
            raise TimeoutError
        usage = SimpleNamespace(requests=1, input_tokens=10, output_tokens=5)
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(usage=usage),
            final_output=RecommendationDraft(
                action=RecommendationAction.HOLD,
                rationale="Hold.",
            ),
        )

    monkeypatch.setattr("pricing_copilot.orchestration.runtime.Runner.run", _run)
    output = asyncio.run(
        runtime.run(agent, "test", output_contract="RecommendationDraft")
    )
    trace = recorder.complete("completed")
    assert isinstance(output, RecommendationDraft)
    assert calls == 2
    assert seen_max_turns == [settings.max_agent_turns, settings.max_agent_turns]
    assert sum(event.kind is TraceEventKind.RETRY for event in trace.events) == 1


def test_tool_call_hook_blocks_excessive_tool_use() -> None:
    settings = Settings(local_tracing_enabled=False, max_tool_calls_per_agent=1)
    recorder = _recorder(settings)
    hooks = BoundedRunHooks(
        agent_name="claims-specialist",
        max_tool_calls=1,
        recorder=recorder,
    )
    tool = SimpleNamespace(name="get_claims_metrics")
    asyncio.run(hooks.on_tool_start(None, None, tool))
    with pytest.raises(RuntimeLimitExceeded, match="tool-call limit"):
        asyncio.run(hooks.on_tool_start(None, None, tool))
    recorder.complete("failed_safe")


def test_invalid_structured_output_gets_one_retry_then_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    azure_chat_model: OpenAIChatCompletionsModel,
) -> None:
    settings = Settings(local_tracing_enabled=False, max_retries=1)
    recorder = _recorder(settings)
    runtime = AgentRuntime(settings, recorder)
    agent = Agent(
        name="governance-agent",
        instructions="Review.",
        tools=[],
        output_type=GovernanceReview,
        model=azure_chat_model,
    )
    calls = 0

    async def _invalid(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ModelBehaviorError("invalid structured output")

    monkeypatch.setattr("pricing_copilot.orchestration.runtime.Runner.run", _invalid)
    with pytest.raises(ModelBehaviorError, match="invalid structured output"):
        asyncio.run(runtime.run(agent, "test", output_contract="GovernanceReview"))
    trace = recorder.complete("failed_safe")
    assert calls == 2
    assert sum(event.kind is TraceEventKind.RETRY for event in trace.events) == 1
