from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from agents import RunConfig
from agents.tracing import TracingProcessor, gen_trace_id, set_trace_processors

from pricing_copilot.config import Settings
from pricing_copilot.observability.contracts import (
    TokenUsage,
    TraceEvent,
    TraceEventKind,
    WorkflowExecutionTrace,
)

WORKFLOW_NAME = "Governed Pricing Decision Copilot"
PROMPT_VERSION = "governed-prompts-v2"
TOOL_VERSION = "deterministic-read-only-tools-v2"
POLICY_VERSION = "recommendation-policy-v2"

_PROCESSOR_LOCK = threading.Lock()
_PROCESSOR_CONFIGURED = False
_ACTIVE_RECORDERS: dict[str, WorkflowTraceRecorder] = {}


class WorkflowTraceRecorder:
    def __init__(self, settings: Settings, configuration_versions: dict[str, Any]) -> None:
        self.settings = settings
        self.trace_id = gen_trace_id()
        self.started_at = datetime.now(UTC)
        self._started_monotonic = monotonic()
        self._events: list[TraceEvent] = []
        self._usage = TokenUsage(
            pricing_configured=(
                settings.cost.input_cost_per_million_tokens_gbp > 0
                or settings.cost.output_cost_per_million_tokens_gbp > 0
            )
        )
        self._configuration_versions = {
            key: value
            for key, value in configuration_versions.items()
            if isinstance(value, str | int | float | bool)
        }
        _ACTIVE_RECORDERS[self.trace_id] = self

    def event(
        self,
        kind: TraceEventKind,
        name: str,
        status: str,
        *,
        duration_ms: float | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self._events.append(
            TraceEvent(
                timestamp=datetime.now(UTC),
                kind=kind,
                name=name,
                status=status,
                duration_ms=duration_ms,
                details=details or {},
            )
        )

    def add_usage(
        self, *, requests: int, input_tokens: int, output_tokens: int, agent_name: str
    ) -> None:
        total = input_tokens + output_tokens
        cost = (
            input_tokens * self.settings.cost.input_cost_per_million_tokens_gbp
            + output_tokens * self.settings.cost.output_cost_per_million_tokens_gbp
        ) / 1_000_000
        self._usage.requests += requests
        self._usage.input_tokens += input_tokens
        self._usage.output_tokens += output_tokens
        self._usage.total_tokens += total
        self._usage.estimated_cost_gbp += cost
        self.event(
            TraceEventKind.MODEL_CALL,
            agent_name,
            "completed",
            details={
                "requests": requests,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total,
                "estimated_cost_gbp": round(cost, 8),
            },
        )

    def run_config(self) -> RunConfig:
        return RunConfig(
            tracing_disabled=not self.settings.agents_sdk_tracing_enabled,
            trace_include_sensitive_data=False,
            workflow_name=WORKFLOW_NAME,
            trace_id=self.trace_id,
            trace_metadata={
                "policy_version": str(self._configuration_versions["policy_version"]),
                "agent_registry_version": str(
                    self._configuration_versions["agent_registry_version"]
                ),
            },
        )

    def complete(self, status: str) -> WorkflowExecutionTrace:
        completed_at = datetime.now(UTC)
        trace = WorkflowExecutionTrace(
            trace_id=self.trace_id,
            workflow_name=WORKFLOW_NAME,
            started_at=self.started_at,
            completed_at=completed_at,
            status=status,
            configuration_versions=self._configuration_versions,
            limits={
                "max_agent_turns": self.settings.max_agent_turns,
                "max_tool_calls_per_agent": self.settings.max_tool_calls_per_agent,
                "tool_timeout_seconds": self.settings.tool_timeout_seconds,
                "request_timeout_seconds": self.settings.request_timeout_seconds,
                "max_workflow_seconds": self.settings.max_workflow_seconds,
                "max_retries": self.settings.max_retries,
            },
            usage=self._usage,
            events=self._events,
        )
        if self.settings.local_tracing_enabled:
            self._write(trace)
        _ACTIVE_RECORDERS.pop(self.trace_id, None)
        return trace

    def _write(self, trace: WorkflowExecutionTrace) -> None:
        directory = Path(self.settings.trace_directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{trace.trace_id}.json"
        path.write_text(trace.model_dump_json(indent=2))

    @property
    def elapsed_ms(self) -> float:
        return (monotonic() - self._started_monotonic) * 1000


class _LocalAgentsSdkTraceProcessor(TracingProcessor):
    def on_trace_start(self, trace: Any) -> None:
        recorder = _ACTIVE_RECORDERS.get(trace.trace_id)
        if recorder is not None:
            recorder.event(TraceEventKind.AGENTS_SDK, "trace", "started")

    def on_trace_end(self, trace: Any) -> None:
        recorder = _ACTIVE_RECORDERS.get(trace.trace_id)
        if recorder is not None:
            recorder.event(TraceEventKind.AGENTS_SDK, "trace", "completed")

    def on_span_start(self, span: Any) -> None:
        recorder = _ACTIVE_RECORDERS.get(span.trace_id)
        if recorder is not None:
            recorder.event(
                TraceEventKind.AGENTS_SDK,
                str(getattr(span.span_data, "type", "span")),
                "started",
            )

    def on_span_end(self, span: Any) -> None:
        recorder = _ACTIVE_RECORDERS.get(span.trace_id)
        if recorder is not None:
            error = getattr(span, "error", None)
            recorder.event(
                TraceEventKind.AGENTS_SDK,
                str(getattr(span.span_data, "type", "span")),
                "failed" if error else "completed",
                details={"has_error": bool(error)},
            )

    def shutdown(self) -> None:
        return None

    def force_flush(self) -> None:
        return None


def configure_local_agents_sdk_tracing() -> None:
    global _PROCESSOR_CONFIGURED
    with _PROCESSOR_LOCK:
        if _PROCESSOR_CONFIGURED:
            return
        set_trace_processors([_LocalAgentsSdkTraceProcessor()])
        _PROCESSOR_CONFIGURED = True


def read_trace(path: Path) -> WorkflowExecutionTrace:
    return WorkflowExecutionTrace.model_validate(json.loads(path.read_text()))
