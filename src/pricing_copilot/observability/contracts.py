from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TraceEventKind(StrEnum):
    WORKFLOW = "workflow"
    ROUTING = "routing"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    GUARDRAIL = "guardrail"
    RETRY = "retry"
    FAILURE = "failure"
    AGENTS_SDK = "agents_sdk"


class TraceEvent(BaseModel):
    timestamp: datetime
    kind: TraceEventKind
    name: str
    status: str
    duration_ms: float | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_gbp: float = 0.0
    pricing_configured: bool = False


class WorkflowExecutionTrace(BaseModel):
    trace_id: str
    workflow_name: str
    started_at: datetime
    completed_at: datetime
    status: str
    configuration_versions: dict[str, str | int | float | bool]
    limits: dict[str, int | float]
    usage: TokenUsage
    events: list[TraceEvent] = Field(default_factory=list)
