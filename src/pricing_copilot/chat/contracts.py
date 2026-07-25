from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pricing_copilot.contracts import ScenarioName, WorkflowResult


class ChatIntent(StrEnum):
    DATA_RETRIEVAL = "data_retrieval"
    MULTI_SOURCE_SUMMARY = "multi_source_summary"
    PRICING_ANALYSIS = "pricing_analysis"
    EVALUATION = "evaluation"
    DRIFT = "drift"
    HELP = "help"
    UNSUPPORTED = "unsupported"


class ActivityStatus(StrEnum):
    SCHEDULED = "scheduled"
    WORKING = "working"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ChatActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ActivityStatus
    label: str
    purpose: str
    agent: str | None = None
    source: str | None = None
    trace_id: str | None = None
    duration_ms: float | None = None


class ChatTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    columns: list[str]
    rows: list[list[str | int | float | None]]


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioName = ScenarioName.CONTROLLED_INCREASE


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1_000)
    context: ChatContext = Field(default_factory=ChatContext)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: ChatIntent
    message: str
    context: ChatContext
    activities: list[ChatActivity] = Field(default_factory=list)
    tables: list[ChatTable] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    investigation_areas: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    refused: bool = False
    workflow_result: WorkflowResult | None = None
