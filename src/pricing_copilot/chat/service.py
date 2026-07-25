"""Safe, typed chat routing over permitted portfolio-level sources."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date
from time import monotonic

from pricing_copilot.chat.contracts import (
    ActivityStatus,
    ChatActivity,
    ChatContext,
    ChatIntent,
    ChatResponse,
    ChatTable,
)
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ResultSource,
    ScenarioName,
    Segment,
)
from pricing_copilot.data.persistent import (
    SOURCE_TABLES,
    PersistentAnalyticsDatabase,
    QueryResult,
)
from pricing_copilot.documents.corpus import SourceType
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.governance.security import quarantine_unsafe_documents
from pricing_copilot.observability.contracts import TraceEvent, TraceEventKind
from pricing_copilot.replay.store import (
    ReplayArtifactIncompatibleError,
    ReplayArtifactMissingError,
    load_replay_artifact,
)
from pricing_copilot.workflow import run_portfolio_workflow

ActivityListener = Callable[[ChatActivity], None]

CLAIMS_LABEL = "Getting information from claims performance data"
CONVERSION_LABEL = "Getting information from conversion performance data"
COMPETITOR_LABEL = "Getting information from competitor information data"
MARKET_INTELLIGENCE_LABEL = "Market intelligence gathering"
PRICING_HISTORY_LABEL = "Checking previous pricing actions"
CUSTOMER_FEEDBACK_LABEL = "Checking customer feedback"

_SOURCE_LABELS: dict[str, str] = {
    "claims": CLAIMS_LABEL,
    "conversion": CONVERSION_LABEL,
    "competitors": COMPETITOR_LABEL,
    "pricing_history": PRICING_HISTORY_LABEL,
    "market_intelligence": MARKET_INTELLIGENCE_LABEL,
    "customer_feedback": CUSTOMER_FEEDBACK_LABEL,
    "schema_catalogue": "Checking the portfolio data catalogue",
}
_SOURCE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claims", ("claims", "loss ratio", "severity", "frequency", "incurred loss")),
    ("conversion", ("conversion", "retention", "quotes", "sales", "renewal rate")),
    ("competitors", ("competitor", "market price", "price index", "competitive")),
    ("pricing_history", ("previous pricing", "pricing history", "previous action", "past action")),
    ("market_intelligence", ("market intelligence", "market report", "repair cost", "broker")),
    ("customer_feedback", ("customer feedback", "feedback", "complaint", "affordability")),
    ("schema_catalogue", ("schema", "data catalogue", "database fields", "available fields")),
)
_SQL_PATTERN = re.compile(
    r"\b(?:select|insert|update|delete|drop|alter|attach|copy|pragma|create|grant|revoke)\b",
    re.IGNORECASE,
)
_UNSAFE_QUERY_PATTERN = re.compile(
    r"\b(?:ignore (?:all |any )?(?:prior|previous|system) instructions|"
    r"(?:weaken|disable|bypass|ignore).{0,40}(?:policy|limit|guardrail)|"
    r"(?:add|create|enable|call|use) (?:a )?(?:new )?(?:tool|agent)|"
    r"(?:exfiltrat|reveal|print|send|upload).{0,40}"
    r"(?:secret|credential|api key|environment variable|customer data))\b",
    re.IGNORECASE,
)
_CUSTOMER_PATTERN = re.compile(
    r"\b(?:customer|policyholder)[ _-]?(?:id|name|record|data)|"
    r"\b(?:date of birth|email address|phone number|postcode)\b",
    re.IGNORECASE,
)


class ChatService:
    """Routes natural language only to an allowlisted read-only data surface."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = PersistentAnalyticsDatabase(self.settings.analytics_database_path)

    def submit(
        self,
        message: str,
        context: ChatContext | None = None,
        *,
        on_activity: ActivityListener | None = None,
    ) -> ChatResponse:
        active_context = context or ChatContext()
        normalized = " ".join(message.split())
        if refusal_reason := self._refusal_reason(normalized):
            return ChatResponse(
                intent=ChatIntent.UNSUPPORTED,
                message=refusal_reason,
                context=active_context,
                refused=True,
            )

        active_context = ChatContext(
            scenario=self._scenario_for(normalized, active_context.scenario),
            force_replay=active_context.force_replay,
        )
        intent = ChatIntent.REPLAY if active_context.force_replay else self._intent_for(normalized)
        sources = self._sources_for(normalized)

        if intent is ChatIntent.REPLAY:
            return self._run_replay(active_context, on_activity)
        if intent is ChatIntent.EVALUATION:
            return self._unavailable(
                intent,
                active_context,
                "Evaluation replay is not available yet. This chat can retrieve governed portfolio "
                "data and run the current governed pricing workflow.",
                on_activity,
            )
        if intent is ChatIntent.DRIFT:
            return self._unavailable(
                intent,
                active_context,
                "Continuous evaluation and model-drift monitoring will be available after "
                "evaluation replay is implemented. No drift result is being inferred from "
                "this chat.",
                on_activity,
            )
        if intent is ChatIntent.HELP:
            return ChatResponse(
                intent=intent,
                context=active_context,
                message=(
                    "Ask about claims, conversion, competitors, previous pricing actions, market "
                    "intelligence, or aggregate customer feedback. Ask for a pricing "
                    "recommendation to run the governed specialist workflow, or say ‘analyse "
                    "everything’ to consult "
                    "every source."
                ),
            )
        if intent is ChatIntent.PRICING_ANALYSIS:
            return self._run_pricing_analysis(normalized, active_context, on_activity)
        if not sources:
            return ChatResponse(
                intent=ChatIntent.DATA_RETRIEVAL,
                context=active_context,
                message=(
                    "Which permitted portfolio-level source should I check? You can ask about "
                    "claims, "
                    "conversion, competitors, previous pricing actions, market intelligence, or "
                    "aggregate customer feedback."
                ),
                requires_clarification=True,
            )
        return self._retrieve_sources(sources, normalized, active_context, on_activity)

    def _refusal_reason(self, message: str) -> str | None:
        if _SQL_PATTERN.search(message):
            return (
                "I cannot accept raw SQL. Ask a natural-language question about the allowlisted, "
                "read-only portfolio sources instead."
            )
        if _UNSAFE_QUERY_PATTERN.search(message):
            return (
                "I cannot weaken controls, change tools, or reveal sensitive system data. "
                "I can help with governed portfolio-level analysis."
            )
        if _CUSTOMER_PATTERN.search(message):
            return (
                "I cannot retrieve customer-level or personal data. I can provide aggregate "
                "portfolio-level information only."
            )
        protected = "|".join(
            re.escape(attribute) for attribute in self.settings.policy.prohibited_attributes
        )
        if protected and re.search(rf"\b(?:{protected})\b", message, re.IGNORECASE):
            return (
                "I cannot use protected attributes in pricing analysis. I can use the permitted "
                "portfolio-level evidence instead."
            )
        return None

    @staticmethod
    def _scenario_for(message: str, fallback: ScenarioName) -> ScenarioName:
        lowered = message.lower()
        if "retention concern" in lowered or "retention scenario" in lowered:
            return ScenarioName.RETENTION_CONCERN
        if "conflicting evidence" in lowered or "conflicting scenario" in lowered:
            return ScenarioName.CONFLICTING_EVIDENCE
        if "controlled increase" in lowered or "controlled scenario" in lowered:
            return ScenarioName.CONTROLLED_INCREASE
        return fallback

    @staticmethod
    def _intent_for(message: str) -> ChatIntent:
        lowered = message.lower()
        if any(word in lowered for word in ("evaluate", "evaluation", "golden case")):
            return ChatIntent.EVALUATION
        if any(phrase in lowered for phrase in ("replay", "cached run", "use the cache")):
            return ChatIntent.REPLAY
        if any(word in lowered for word in ("drift", "monitoring", "monitor model")):
            return ChatIntent.DRIFT
        if any(word in lowered for word in ("help", "what can you", "how do i")):
            return ChatIntent.HELP
        pricing_keywords = (
            "recommend",
            "should we",
            "analyse everything",
            "analyze everything",
        )
        if any(word in lowered for word in pricing_keywords):
            return ChatIntent.PRICING_ANALYSIS
        if len(ChatService._sources_for(message)) > 1:
            return ChatIntent.MULTI_SOURCE_SUMMARY
        return ChatIntent.DATA_RETRIEVAL

    @staticmethod
    def _sources_for(message: str) -> list[str]:
        lowered = message.lower()
        return [
            source
            for source, keywords in _SOURCE_KEYWORDS
            if any(keyword in lowered for keyword in keywords)
        ]

    def _emit(
        self,
        activity: ChatActivity,
        activities: list[ChatActivity],
        listener: ActivityListener | None,
    ) -> None:
        activities.append(activity)
        if listener is not None:
            listener(activity)

    def _unavailable(
        self,
        intent: ChatIntent,
        context: ChatContext,
        message: str,
        listener: ActivityListener | None,
    ) -> ChatResponse:
        activity = ChatActivity(
            status=ActivityStatus.UNAVAILABLE,
            label="Requested capability is not available",
            purpose="Reporting the current governed capability boundary.",
        )
        activities: list[ChatActivity] = []
        self._emit(activity, activities, listener)
        return ChatResponse(intent=intent, message=message, context=context, activities=activities)

    def _run_replay(
        self, context: ChatContext, listener: ActivityListener | None
    ) -> ChatResponse:
        activities: list[ChatActivity] = []
        try:
            artifact = load_replay_artifact(context.scenario, self.settings)
        except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.UNAVAILABLE,
                    label="Replay is not available for this scenario",
                    purpose="Reporting that no valid replay artifact is recorded.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.REPLAY,
                context=context,
                message=(
                    f"A replay is not available for the {context.scenario.value} scenario yet "
                    f"({exc}). Ask for a live recommendation instead, or record a replay "
                    "artifact first."
                ),
                activities=activities,
            )
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label="Replaying a previously validated cached run",
                purpose="Serving a version-checked replay artifact instead of a live model call.",
            ),
            activities,
            listener,
        )
        response = artifact.chat_response
        return response.model_copy(
            update={
                "intent": ChatIntent.REPLAY,
                "message": f"**[REPLAY - not a live analysis]** {response.message}",
                "activities": activities,
                "source": ResultSource.REPLAY,
                "workflow_result": (
                    response.workflow_result.model_copy(update={"source": ResultSource.REPLAY})
                    if response.workflow_result is not None
                    else None
                ),
                "context": context,
            }
        )

    def _retrieve_sources(
        self,
        sources: Iterable[str],
        message: str,
        context: ChatContext,
        listener: ActivityListener | None,
    ) -> ChatResponse:
        activities: list[ChatActivity] = []
        tables: list[ChatTable] = []
        evidence_ids: list[str] = []
        for source in sources:
            label = _SOURCE_LABELS[source]
            self._emit(
                ChatActivity(
                    status=ActivityStatus.WORKING,
                    label=label,
                    purpose=(
                        "Retrieving permitted portfolio-level evidence for the current scenario."
                    ),
                    source=source,
                ),
                activities,
                listener,
            )
            started = monotonic()
            if source == "schema_catalogue":
                table = self._catalogue_table()
            elif source in {"market_intelligence", "customer_feedback"}:
                table, document_ids = self._retrieve_documents(source, context.scenario)
                evidence_ids.extend(document_ids)
            else:
                table = self._query_table(
                    source,
                    context.scenario,
                    requested_fields=self._requested_fields(source, message),
                )
            tables.append(table)
            self._emit(
                ChatActivity(
                    status=ActivityStatus.COMPLETED,
                    label=label,
                    purpose="Permitted portfolio-level evidence is ready to review.",
                    source=source,
                    duration_ms=round((monotonic() - started) * 1_000, 1),
                ),
                activities,
                listener,
            )
        source_names = ", ".join(table.title.lower() for table in tables)
        return ChatResponse(
            intent=(
                ChatIntent.MULTI_SOURCE_SUMMARY if len(tables) > 1 else ChatIntent.DATA_RETRIEVAL
            ),
            context=context,
            message=(
                f"I retrieved permitted portfolio-level information from {source_names} for the "
                f"{context.scenario.value} scenario. The tables below retain the source fields so "
                "you can inspect the evidence directly."
            ),
            activities=activities,
            tables=tables,
            cited_evidence_ids=evidence_ids,
        )

    def _query_table(
        self, source: str, scenario: ScenarioName, *, requested_fields: list[str] | None
    ) -> ChatTable:
        result = self.database.query_source(source, scenario, columns=requested_fields)
        return self._table_from_query(result)

    @staticmethod
    def _requested_fields(source: str, message: str) -> list[str] | None:
        """Use explicit permitted field names when the analyst asks for them."""
        lowered = message.lower()
        requested = [field for field in SOURCE_TABLES[source] if field in lowered]
        return requested or None

    def _catalogue_table(self) -> ChatTable:
        catalogue = self.database.schema_catalogue()
        rows = [
            [table["name"], column["name"], column["data_type"], column["unit"]]
            for table in catalogue["tables"]
            if isinstance(table, dict)
            for column in table["columns"]
            if isinstance(column, dict) and column["name"] != "scenario"
        ]
        return ChatTable(
            title="Portfolio Data Catalogue",
            columns=["source", "field", "data_type", "unit"],
            rows=rows,
        )

    @staticmethod
    def _table_from_query(result: QueryResult) -> ChatTable:
        rows: list[list[str | int | float | None]] = []
        for row in result.rows:
            rows.append(
                [
                    value.isoformat()
                    if isinstance(value, date)
                    else value
                    if isinstance(value, str | int | float) or value is None
                    else str(value)
                    for value in row
                ]
            )
        return ChatTable(
            title=result.source.replace("_", " ").title(),
            columns=list(result.columns),
            rows=rows,
        )

    @staticmethod
    def _retrieve_documents(source: str, scenario: ScenarioName) -> tuple[ChatTable, list[str]]:
        retrieved = retrieve_documents(
            scenario=scenario,
            region=Region.NORTH_WEST,
            query="portfolio pricing market intelligence customer feedback",
            top_k=12,
        )
        safe_documents, _ = quarantine_unsafe_documents(retrieved)
        selected = [
            document
            for document in safe_documents
            if (
                document.document.source_type is SourceType.CUSTOMER_FEEDBACK
                if source == "customer_feedback"
                else document.document.source_type is not SourceType.CUSTOMER_FEEDBACK
            )
        ]
        rows: list[list[str | int | float | None]] = [
            [
                document.document.document_id,
                document.document.source_type.value,
                document.document.title,
                document.document.source_date.isoformat(),
                document.document.sentiment.value,
            ]
            for document in selected
        ]
        return (
            ChatTable(
                title=(
                    "Customer Feedback" if source == "customer_feedback" else "Market Intelligence"
                ),
                columns=["document_id", "source_type", "title", "source_date", "sentiment"],
                rows=rows,
            ),
            [document.document.document_id for document in selected],
        )

    def _run_pricing_analysis(
        self,
        message: str,
        context: ChatContext,
        listener: ActivityListener | None,
    ) -> ChatResponse:
        activities: list[ChatActivity] = []

        def record_trace_event(event: TraceEvent) -> None:
            activity = self._activity_from_trace(event)
            if activity is not None:
                self._emit(activity, activities, listener)

        self._emit(
            ChatActivity(
                status=ActivityStatus.SCHEDULED,
                label="Supervisor coordinating specialist agents",
                purpose=(
                    "Coordinating market intelligence, claims, conversion, pricing history, "
                    "recommendation, and governance."
                ),
                agent="portfolio-supervisor",
            ),
            activities,
            listener,
        )
        question = PortfolioQuestion(
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            analysis_period=AnalysisPeriod(
                start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)
            ),
            scenario=context.scenario,
        )
        result = run_portfolio_workflow(question, self.settings, event_listener=record_trace_event)
        live_failure_reason = next(
            (
                item.reason
                for item in result.missing_evidence
                if item.reason.startswith("workflow:")
            ),
            None,
        )
        if live_failure_reason is not None:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.FAILED,
                    label="Live analysis is currently unavailable",
                    purpose="Reporting a live failure without silently switching to replay.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.PRICING_ANALYSIS,
                context=context,
                message=(
                    f"Live analysis could not complete right now ({live_failure_reason}). Ask "
                    f"me to 'replay the {context.scenario.value} scenario' to see a previously "
                    "validated, clearly labeled cached run instead."
                ),
                activities=activities,
            )
        recommendation = result.recommendation
        message_summary = (
            f"The governed workflow recommends **{recommendation.action.value}**. "
            f"{recommendation.rationale} This is decision support only and needs an analyst’s "
            "explicit confirmation before any action is recorded."
        )
        return ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=context,
            message=message_summary,
            activities=activities,
            cited_evidence_ids=recommendation.cited_evidence_ids,
            investigation_areas=recommendation.investigation_areas,
            workflow_result=result,
        )

    @staticmethod
    def _activity_from_trace(event: TraceEvent) -> ChatActivity | None:
        label_by_name = {
            "claims-specialist": CLAIMS_LABEL,
            "conversion-specialist": CONVERSION_LABEL,
            "market-intelligence-specialist": MARKET_INTELLIGENCE_LABEL,
            "pricing-history-specialist": PRICING_HISTORY_LABEL,
            "recommendation-agent": "Preparing a governed pricing recommendation",
            "governance-agent": "Checking recommendation governance",
            "portfolio-supervisor": "Supervisor coordinating specialist agents",
        }
        allowed_kinds = {
            TraceEventKind.ROUTING,
            TraceEventKind.TOOL_CALL,
            TraceEventKind.MODEL_CALL,
            TraceEventKind.GUARDRAIL,
            TraceEventKind.FAILURE,
        }
        if event.kind not in allowed_kinds:
            return None
        label = label_by_name.get(event.name)
        if label is None and event.kind is TraceEventKind.TOOL_CALL:
            name = event.name.lower()
            if "claim" in name:
                label = CLAIMS_LABEL
            elif "conversion" in name:
                label = CONVERSION_LABEL
            elif "competitor" in name:
                label = COMPETITOR_LABEL
            elif "pricing" in name:
                label = PRICING_HISTORY_LABEL
            elif "document" in name or "market" in name:
                label = MARKET_INTELLIGENCE_LABEL
        if label is None:
            return None
        status = {
            "started": ActivityStatus.WORKING,
            "scheduled": ActivityStatus.SCHEDULED,
            "completed": ActivityStatus.COMPLETED,
            "blocked": ActivityStatus.BLOCKED,
            "failed": ActivityStatus.FAILED,
            "failed_safe": ActivityStatus.FAILED,
        }.get(event.status, ActivityStatus.WORKING)
        return ChatActivity(
            status=status,
            label=label,
            purpose=(
                "Showing governed workflow activity without exposing private prompts or "
                "chain-of-thought."
            ),
            agent=event.name if "agent" in event.name or "specialist" in event.name else None,
            trace_id=None,
            duration_ms=event.duration_ms,
        )
