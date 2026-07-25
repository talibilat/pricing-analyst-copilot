from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from agents import Agent, RunHooks, Runner
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError, ToolTimeoutError

from pricing_copilot.config import Settings
from pricing_copilot.governance.registry import require_approved_agent
from pricing_copilot.observability.contracts import TraceEventKind
from pricing_copilot.observability.trace import WorkflowTraceRecorder


class RuntimeLimitExceeded(RuntimeError):
    """Raised when an agent exceeds a configured operational bound."""


class BoundedRunHooks(RunHooks[Any]):
    def __init__(
        self, *, agent_name: str, max_tool_calls: int, recorder: WorkflowTraceRecorder
    ) -> None:
        self.agent_name = agent_name
        self.max_tool_calls = max_tool_calls
        self.recorder = recorder
        self.tool_calls = 0
        self.model_calls = 0
        self._tool_started_at: dict[str, float] = {}

    async def on_llm_start(
        self, context: Any, agent: Any, system_prompt: str | None, input_items: list[Any]
    ) -> None:
        self.model_calls += 1
        self.recorder.event(
            TraceEventKind.MODEL_CALL,
            self.agent_name,
            "started",
            details={"model_call": self.model_calls},
        )

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        self.tool_calls += 1
        tool_name = str(tool.name)
        if self.tool_calls > self.max_tool_calls:
            self.recorder.event(
                TraceEventKind.GUARDRAIL,
                "tool_call_limit",
                "blocked",
                details={
                    "agent": self.agent_name,
                    "configured_limit": self.max_tool_calls,
                    "attempted_call": self.tool_calls,
                },
            )
            raise RuntimeLimitExceeded(
                f"{self.agent_name} exceeded the {self.max_tool_calls}-tool-call limit."
            )
        self._tool_started_at[tool_name] = monotonic()
        self.recorder.event(
            TraceEventKind.TOOL_CALL,
            tool_name,
            "started",
            details={"agent": self.agent_name, "tool_call": self.tool_calls},
        )

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: object) -> None:
        tool_name = str(tool.name)
        started_at = self._tool_started_at.pop(tool_name, monotonic())
        self.recorder.event(
            TraceEventKind.TOOL_CALL,
            tool_name,
            "completed",
            duration_ms=(monotonic() - started_at) * 1000,
            details={"agent": self.agent_name},
        )


class AgentRuntime:
    def __init__(self, settings: Settings, recorder: WorkflowTraceRecorder) -> None:
        self.settings = settings
        self.recorder = recorder

    async def run(
        self,
        agent: Agent[Any],
        prompt: str,
        *,
        output_contract: str,
    ) -> object:
        tool_names = {tool.name for tool in agent.tools}
        actual_output_contract = getattr(agent.output_type, "__name__", str(agent.output_type))
        if actual_output_contract != output_contract:
            raise RuntimeLimitExceeded(
                f"{agent.name} is configured with output contract {actual_output_contract!r}, "
                f"not the requested {output_contract!r}."
            )
        require_approved_agent(
            agent.name, tool_names=tool_names, output_contract=output_contract
        )
        if agent.handoffs:
            raise RuntimeLimitExceeded(
                f"{agent.name} declares handoffs, but runtime agent creation and handoffs are "
                "prohibited by this controlled manager workflow."
            )

        retryable = (TimeoutError, MaxTurnsExceeded, ModelBehaviorError, ToolTimeoutError)
        attempts = self.settings.max_retries + 1
        for attempt in range(attempts):
            hooks = BoundedRunHooks(
                agent_name=agent.name,
                max_tool_calls=self.settings.max_tool_calls_per_agent,
                recorder=self.recorder,
            )
            started_at = monotonic()
            try:
                result = await asyncio.wait_for(
                    Runner.run(
                        agent,
                        prompt,
                        max_turns=self.settings.max_agent_turns,
                        hooks=hooks,
                        run_config=self.recorder.run_config(),
                    ),
                    timeout=self.settings.request_timeout_seconds,
                )
            except retryable as exc:
                self.recorder.event(
                    TraceEventKind.FAILURE,
                    agent.name,
                    "failed",
                    duration_ms=(monotonic() - started_at) * 1000,
                    details={"error_type": type(exc).__name__, "attempt": attempt + 1},
                )
                if attempt >= self.settings.max_retries:
                    raise
                self.recorder.event(
                    TraceEventKind.RETRY,
                    agent.name,
                    "scheduled",
                    details={"retry_number": attempt + 1, "reason": type(exc).__name__},
                )
                continue

            usage = result.context_wrapper.usage
            self.recorder.add_usage(
                requests=usage.requests,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                agent_name=agent.name,
            )
            self.recorder.event(
                TraceEventKind.ROUTING,
                agent.name,
                "completed",
                duration_ms=(monotonic() - started_at) * 1000,
                details={
                    "turn_limit": self.settings.max_agent_turns,
                    "tool_calls": hooks.tool_calls,
                    "model_calls": hooks.model_calls,
                    "attempt": attempt + 1,
                },
            )
            return result.final_output

        raise AssertionError("Agent run exhausted attempts without returning or raising.")
