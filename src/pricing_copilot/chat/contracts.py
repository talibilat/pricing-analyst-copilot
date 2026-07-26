from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pricing_copilot.contracts import (
    Product,
    Region,
    ResultSource,
    ScenarioName,
    Segment,
    WorkflowResult,
)


class ChatIntent(StrEnum):
    GENERAL_ANSWER = "general_answer"
    CLARIFICATION = "clarification"
    DATA_RETRIEVAL = "data_retrieval"
    MULTI_SOURCE_SUMMARY = "multi_source_summary"
    PRICING_ANALYSIS = "pricing_analysis"
    REPLAY = "replay"
    EVALUATION = "evaluation"
    DRIFT = "drift"
    HELP = "help"
    UNSUPPORTED = "unsupported"


class ConversationRoute(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    CLARIFY = "clarify"
    TOOL_CALL = "tool_call"
    REFUSE = "refuse"


class ChatToolName(StrEnum):
    ANALYTICS = "analytics"
    SCHEMA = "schema"
    DOCUMENTS = "documents"
    REPLAY = "replay"
    EVALUATION = "evaluation"
    DRIFT = "drift"
    RECOMMENDATION = "recommendation"
    READ_ONLY_SQL = "read_only_sql"


class AnalyticsSource(StrEnum):
    CLAIMS = "claims"
    CONVERSION = "conversion"
    COMPETITORS = "competitors"
    PRICING_HISTORY = "pricing_history"
    MARKET_INTELLIGENCE = "market_intelligence"
    CUSTOMER_FEEDBACK = "customer_feedback"


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class ConversationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: ConversationRoute
    response: str | None = None
    clarification_question: str | None = None
    tool_name: ChatToolName | None = None
    sources: list[AnalyticsSource] = Field(default_factory=list)
    requested_fields: list[str] = Field(default_factory=list)
    sql: str | None = None
    document_query: str | None = None
    scenario: ScenarioName | None = None
    product: Product | None = None
    region: Region | None = None
    segment: Segment | None = None
    start_month: date | None = None
    end_month: date | None = None
    limitations: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "For clarify routes, two or three literal user replies that each make a concrete "
            "choice and can be submitted unchanged."
        ),
    )

    @model_validator(mode="after")
    def validate_route_payload(self) -> ConversationDecision:
        if self.route in (ConversationRoute.DIRECT_ANSWER, ConversationRoute.REFUSE):
            if not self.response:
                raise ValueError(f"{self.route.value} requires response")
        if self.route is ConversationRoute.CLARIFY and not self.clarification_question:
            raise ValueError("clarify requires clarification_question")
        if self.route is ConversationRoute.TOOL_CALL and self.tool_name is None:
            raise ValueError("tool_call requires tool_name")
        if (
            self.start_month is not None
            and self.end_month is not None
            and self.end_month < self.start_month
        ):
            raise ValueError("end_month must not be before start_month")
        return self


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
    force_replay: bool = False
    product: Product = Product.PERSONAL_MOTOR
    region: Region = Region.NORTH_WEST
    segment: Segment | None = None
    analysis_start_month: date | None = None
    analysis_end_month: date | None = None


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)


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
    route: ConversationRoute | None = None
    clarification_question: str | None = None
    limitations: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)
    workflow_result: WorkflowResult | None = None
    source: ResultSource = ResultSource.LIVE
    elapsed_ms: float | None = None
    plan_details: list[str] = Field(default_factory=list)


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1_000)
    history: list[ConversationMessage] = Field(default_factory=list)
    context: ChatContext
    decision: ConversationDecision | None = None
    response: ChatResponse | None = None
