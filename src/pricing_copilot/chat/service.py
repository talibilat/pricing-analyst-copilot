"""Safe, typed chat routing over permitted portfolio-level sources."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from time import monotonic

from pricing_copilot.chat.contracts import (
    ActivityStatus,
    AnalyticsSource,
    ChatActivity,
    ChatContext,
    ChatIntent,
    ChatResponse,
    ChatTable,
    ChatToolName,
    ConversationDecision,
    ConversationMessage,
    ConversationRoute,
)
from pricing_copilot.chat.conversation_graph import (
    AgentsSdkConversationPlanner,
    ConversationGraph,
    ConversationPlanner,
    ConversationToolExecutor,
)
from pricing_copilot.chat.presentation import compose_analysis_response
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
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
from pricing_copilot.recommendation.synthesizer import FakeRecommendationSynthesizer
from pricing_copilot.replay.store import (
    ReplayArtifactIncompatibleError,
    ReplayArtifactMissingError,
    load_replay_artifact,
)
from pricing_copilot.workflow import run_baseline_portfolio_workflow, run_portfolio_workflow

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
_ANALYTICAL_TERMS = (
    "analyse",
    "analyze",
    "compare",
    "decision",
    "deteriorat",
    "driver",
    "driving",
    "identify",
    "last 12",
    "last twelve",
    "performance",
    "recommend",
    "review",
    "rising",
    "trend",
    "why",
    "show",
    "what did",
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


def _format_list(values: Sequence[str]) -> str:
    """Return a human-readable list without exposing implementation syntax."""
    if not values:
        return "no sources"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


class DefaultConversationTools:
    """Adapts the existing governed capabilities to the conversation graph."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = PersistentAnalyticsDatabase(self.settings.analytics_database_path)

    def available_tools(self) -> dict[str, str]:
        return {
            ChatToolName.ANALYTICS.value: (
                "Retrieve allowlisted claims, conversion, competitor, or pricing-history tables."
            ),
            ChatToolName.SCHEMA.value: (
                "Describe approved analytics tables, fields, types, and units."
            ),
            ChatToolName.DOCUMENTS.value: (
                "Search market intelligence or aggregate customer-feedback documents."
            ),
            ChatToolName.REPLAY.value: (
                "Load a version-checked cached recommendation for a scenario."
            ),
            ChatToolName.EVALUATION.value: "Load the latest evaluation benchmark report.",
            ChatToolName.DRIFT.value: "Load the latest drift-monitoring report.",
            ChatToolName.RECOMMENDATION.value: (
                "Run the governed specialist workflow for a pricing recommendation."
            ),
            ChatToolName.READ_ONLY_SQL.value: (
                "Execute validated read-only SQL when the safe SQL adapter is installed."
            ),
        }

    def execute(
        self,
        message: str,
        decision: ConversationDecision,
        context: ChatContext,
        listener: ActivityListener | None,
    ) -> ChatResponse:
        if refusal_reason := self._refusal_reason(message):
            return ChatResponse(
                intent=ChatIntent.UNSUPPORTED,
                message=refusal_reason,
                context=context,
                refused=True,
                route=ConversationRoute.REFUSE,
            )
        if decision.tool_name is ChatToolName.REPLAY:
            return self._run_replay(context, listener)
        if decision.tool_name is ChatToolName.EVALUATION:
            return self._report_evaluation(context, listener)
        if decision.tool_name is ChatToolName.DRIFT:
            return self._report_drift(context, listener)
        if decision.tool_name is ChatToolName.RECOMMENDATION:
            return self._run_pricing_analysis(message, decision, context, listener)
        if decision.tool_name is ChatToolName.SCHEMA:
            return self._retrieve_sources(
                ["schema_catalogue"],
                [],
                context,
                listener,
            )
        if decision.tool_name is ChatToolName.DOCUMENTS:
            if self._is_analytical_request(message):
                return self._run_pricing_analysis(message, decision, context, listener)
            document_sources = [
                source.value
                for source in decision.sources
                if source
                in (
                    AnalyticsSource.MARKET_INTELLIGENCE,
                    AnalyticsSource.CUSTOMER_FEEDBACK,
                )
            ]
            return self._retrieve_sources(
                document_sources or ["market_intelligence", "customer_feedback"],
                [],
                context,
                listener,
            )
        if decision.tool_name is ChatToolName.ANALYTICS:
            sources = [
                source.value
                for source in decision.sources
                if source
                in (
                    AnalyticsSource.CLAIMS,
                    AnalyticsSource.CONVERSION,
                    AnalyticsSource.COMPETITORS,
                    AnalyticsSource.PRICING_HISTORY,
                )
            ]
            if self._is_unique_competitor_name_request(message):
                return self._retrieve_unique_competitor_names(context, listener)
            if self._is_analytical_request(message):
                return self._run_pricing_analysis(message, decision, context, listener)
            if sources:
                return self._retrieve_sources(
                    sources,
                    decision.requested_fields,
                    context,
                    listener,
                )
            return ChatResponse(
                intent=ChatIntent.HELP,
                context=context,
                message=(
                    "Hello! Ask about claims, conversion, competitors, previous pricing actions, "
                    "market intelligence, or request a portfolio review."
                ),
            )
        if decision.tool_name is ChatToolName.READ_ONLY_SQL:
            if self._is_unique_competitor_name_request(message):
                return self._retrieve_unique_competitor_names(context, listener)
            return ChatResponse(
                intent=ChatIntent.UNSUPPORTED,
                context=context,
                message=(
                    "I understood that you want a read-only SQL query, but the validated SQL "
                    "executor is not connected in this workstream yet. I have not executed it."
                ),
                limitations=["The safe read-only SQL adapter is not installed yet."],
                suggested_next_steps=[
                    "Ask for the same data in natural language.",
                    "Connect the read-only SQL adapter from the data-tools workstream.",
                ],
            )
        return ChatResponse(
            intent=ChatIntent.UNSUPPORTED,
            context=context,
            message="The selected capability is not available.",
            limitations=["No registered executor matched the requested tool."],
        )

    @staticmethod
    def _is_unique_competitor_name_request(message: str) -> bool:
        lowered = message.lower()
        return (
            "competitor" in lowered
            and any(term in lowered for term in ("name", "names", "unique", "distinct", "all"))
        )

    def _retrieve_unique_competitor_names(
        self, context: ChatContext, listener: ActivityListener | None
    ) -> ChatResponse:
        """Answer a natural-language lookup without routing it through free-form SQL."""
        activities: list[ChatActivity] = []
        self._emit(
            ChatActivity(
                status=ActivityStatus.WORKING,
                label=COMPETITOR_LABEL,
                purpose="Retrieving the unique names from permitted competitor data.",
                source="competitors",
            ),
            activities,
            listener,
        )
        result = self.database.query_source(
            "competitors", context.scenario, columns=["competitor_name"]
        )
        names = sorted({str(row[0]) for row in result.rows if row and row[0] is not None})
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label=COMPETITOR_LABEL,
                purpose="Unique competitor names are ready to review.",
                source="competitors",
            ),
            activities,
            listener,
        )
        if not names:
            message = "No competitor names are available for the selected portfolio scenario."
        else:
            formatted_names = (
                ", ".join(names[:-1]) + f", and {names[-1]}"
                if len(names) > 1
                else names[0]
            )
            message = f"The unique competitor names are: {formatted_names}."
        return ChatResponse(
            intent=ChatIntent.DATA_RETRIEVAL,
            context=context,
            message=message,
            activities=activities,
            tables=[
                ChatTable(
                    title="Unique competitor names",
                    columns=["competitor_name"],
                    rows=[[name] for name in names],
                )
            ],
        )

    @staticmethod
    def _is_analytical_request(message: str) -> bool:
        """Keep explicit field lookups tabular, but answer portfolio questions as analysis."""
        lowered = message.lower()
        explicit_field_lookup = any(
            field in lowered
            for fields in SOURCE_TABLES.values()
            for field in fields
            if field not in {"period", "product", "region", "segment"}
        )
        return not explicit_field_lookup and (
            "?" in message or any(term in lowered for term in _ANALYTICAL_TERMS)
        )

    def _refusal_reason(self, message: str) -> str | None:
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

    def _run_replay(self, context: ChatContext, listener: ActivityListener | None) -> ChatResponse:
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

    def _report_evaluation(
        self, context: ChatContext, listener: ActivityListener | None
    ) -> ChatResponse:
        from pricing_copilot.evaluation.store import load_benchmark_report

        activities: list[ChatActivity] = []
        report = load_benchmark_report(self.settings)
        if report is None:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.UNAVAILABLE,
                    label="No evaluation report is recorded yet",
                    purpose="Reporting the current evaluation capability boundary.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.EVALUATION,
                context=context,
                message=(
                    "No evaluation has been run yet. Run the CLI with --evaluate to generate a "
                    "report, then ask again."
                ),
                activities=activities,
            )
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label="Loaded the latest evaluation benchmark",
                purpose="Reporting configured targets against actual measured results.",
            ),
            activities,
            listener,
        )
        rows: list[list[str | int | float | None]] = [
            [metric, target_value, getattr(report.governed.actuals, metric, "n/a")]
            for metric, target_value in report.governed.targets.model_dump().items()
        ]
        table = ChatTable(
            title="Governed workflow - targets vs actuals",
            columns=["metric", "target", "actual"],
            rows=rows,
        )
        message = (
            f"Latest evaluation ({report.golden_set_version}, generated "
            f"{report.generated_at.date().isoformat()}): "
            f"{report.governed.actuals.cases_passed} passed, "
            f"{report.governed.actuals.cases_failed} failed, "
            f"{report.governed.actuals.cases_errored} errored out of "
            f"{len(report.governed.case_results)} governed cases."
        )
        return ChatResponse(
            intent=ChatIntent.EVALUATION,
            context=context,
            message=message,
            activities=activities,
            tables=[table],
        )

    def _report_drift(
        self, context: ChatContext, listener: ActivityListener | None
    ) -> ChatResponse:
        from pricing_copilot.drift.store import load_drift_report

        activities: list[ChatActivity] = []
        report = load_drift_report(self.settings)
        if report is None:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.UNAVAILABLE,
                    label="No drift report is recorded yet",
                    purpose="Reporting the current monitoring capability boundary.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.DRIFT,
                context=context,
                message=(
                    "No drift monitoring run has been recorded yet. Run the CLI with "
                    "--monitor-drift to generate a report, then ask again."
                ),
                activities=activities,
            )
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label="Loaded the latest drift monitoring report",
                purpose="Reporting which measures moved and which thresholds were crossed.",
            ),
            activities,
            listener,
        )
        material = report.material_alerts
        rows: list[list[str | int | float | None]] = [
            [
                alert.category.value,
                alert.metric_name,
                alert.breached,
                alert.investigation_required,
                alert.detail,
            ]
            for alert in report.alerts
        ]
        table = ChatTable(
            title="Drift monitoring - data, behavior, operational, and configuration alerts",
            columns=["category", "metric", "breached", "investigation_required", "detail"],
            rows=rows,
        )
        if material:
            message = (
                f"{len(material)} measure(s) crossed their threshold and require investigation: "
                + "; ".join(f"{a.metric_name} ({a.category.value})" for a in material)
                + "."
            )
        else:
            message = "No material drift was detected in the latest monitoring run."
        return ChatResponse(
            intent=ChatIntent.DRIFT,
            context=context,
            message=message,
            activities=activities,
            tables=[table],
        )

    def _retrieve_sources(
        self,
        sources: Iterable[str],
        requested_fields: list[str],
        context: ChatContext,
        listener: ActivityListener | None,
    ) -> ChatResponse:
        activities: list[ChatActivity] = []
        tables: list[ChatTable] = []
        evidence_ids: list[str] = []
        source_list = list(sources)
        for source in source_list:
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
                    requested_fields=[
                        field for field in requested_fields if field in SOURCE_TABLES[source]
                    ]
                    or None,
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
        if source_list == ["schema_catalogue"]:
            table_names = _format_list(
                sorted({str(row[0]) for row in tables[0].rows if row and row[0]})
            )
            message = (
                f"The available portfolio data tables are {table_names}. "
                "Open Supporting data details to view the permitted columns and definitions."
            )
        else:
            source_names = _format_list([table.title.lower() for table in tables])
            message = f"Here is the requested data from {source_names}."
        return ChatResponse(
            intent=(
                ChatIntent.MULTI_SOURCE_SUMMARY if len(tables) > 1 else ChatIntent.DATA_RETRIEVAL
            ),
            context=context,
            message=message,
            activities=activities,
            tables=tables,
            cited_evidence_ids=evidence_ids,
        )

    def _query_table(
        self, source: str, scenario: ScenarioName, *, requested_fields: list[str] | None
    ) -> ChatTable:
        result = self.database.query_source(source, scenario, columns=requested_fields)
        return self._table_from_query(result)

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
        decision: ConversationDecision,
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
                label="Reviewing portfolio evidence",
                purpose="Preparing an integrated claims, commercial, market, and pricing review.",
            ),
            activities,
            listener,
        )
        for label, source in (
            (CLAIMS_LABEL, "claims"),
            (CONVERSION_LABEL, "conversion"),
            (COMPETITOR_LABEL, "competitors"),
            (PRICING_HISTORY_LABEL, "pricing_history"),
            (MARKET_INTELLIGENCE_LABEL, "market_intelligence"),
            (CUSTOMER_FEEDBACK_LABEL, "customer_feedback"),
        ):
            self._emit(
                ChatActivity(
                    status=ActivityStatus.WORKING,
                    label=label,
                    purpose="Comparing the requested portfolio period with its prior window.",
                    source=source,
                ),
                activities,
                listener,
            )
        claims_periods = self.database.query_source(
            "claims",
            context.scenario,
            columns=["period"],
        )
        periods = sorted(
            value for row in claims_periods.rows for value in row if isinstance(value, date)
        )
        if not periods:
            return ChatResponse(
                intent=ChatIntent.PRICING_ANALYSIS,
                context=context,
                message=(
                    "I cannot run a recommendation because no claims period is available for "
                    f"the {context.scenario.value} scenario."
                ),
                limitations=["The required analysis period could not be resolved from the data."],
            )
        selected_segment = context.segment or decision.segment or Segment.RENEWAL
        question = PortfolioQuestion(
            product=context.product,
            region=context.region,
            segment=selected_segment,
            analysis_period=AnalysisPeriod(
                start_month=context.analysis_start_month or periods[max(0, len(periods) - 12)],
                end_month=context.analysis_end_month or periods[-1],
            ),
            scenario=context.scenario,
        )
        if decision.tool_name is ChatToolName.RECOMMENDATION:
            result = run_portfolio_workflow(
                question, self.settings, event_listener=record_trace_event
            )
        else:
            result = run_baseline_portfolio_workflow(
                question, self.settings, FakeRecommendationSynthesizer()
            )
        if result.analytics is None or any(
            item.reason.startswith("workflow:") for item in result.missing_evidence
        ):
            # A specialist-runtime failure must not hide the useful deterministic evidence.
            # The response composer reports the reduced confidence and outstanding limitations.
            result = run_baseline_portfolio_workflow(
                question, self.settings, FakeRecommendationSynthesizer()
            )
        recommendation = result.recommendation
        message_summary = compose_analysis_response(
            result,
            segment_identification_requested=any(
                phrase in message.lower()
                for phrase in ("which segment", "identify the segment", "segment driving")
            ),
            focus=self._focus_for_message(message),
        )
        return ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=context.model_copy(update={"segment": selected_segment}),
            message=message_summary,
            activities=activities,
            cited_evidence_ids=recommendation.cited_evidence_ids,
            investigation_areas=recommendation.investigation_areas,
            workflow_result=result,
        )

    @staticmethod
    def _focus_for_message(message: str) -> str | None:
        source_by_term = (
            ("claims", "claims"),
            ("loss ratio", "claims"),
            ("conversion", "conversion"),
            ("competitor", "competitors"),
            ("pricing history", "pricing_history"),
            ("previous pricing", "pricing_history"),
        )
        matches = {source for term, source in source_by_term if term in message.lower()}
        return next(iter(matches)) if len(matches) == 1 else None

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


class ChatService:
    """Thin application adapter around the LLM-first conversation graph."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        planner: ConversationPlanner | None = None,
        tools: ConversationToolExecutor | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tools = tools or DefaultConversationTools(self.settings)
        self.graph = ConversationGraph(
            planner or AgentsSdkConversationPlanner(self.settings),
            self.tools,
        )

    def submit(
        self,
        message: str,
        context: ChatContext | None = None,
        *,
        history: Sequence[ConversationMessage] = (),
        on_activity: ActivityListener | None = None,
    ) -> ChatResponse:
        active_context = self._resolve_scope(message, context or ChatContext())
        return self.graph.run(
            message,
            active_context,
            history=history,
            on_activity=on_activity,
        )

    @staticmethod
    def _resolve_scope(message: str, context: ChatContext) -> ChatContext:
        """Resolve explicit scope changes while retaining earlier conversation scope."""
        lowered = message.lower()
        updates: dict[str, object] = {}
        if "retention concern" in lowered:
            updates["scenario"] = ScenarioName.RETENTION_CONCERN
        elif "conflicting evidence" in lowered:
            updates["scenario"] = ScenarioName.CONFLICTING_EVIDENCE
        elif "controlled increase" in lowered:
            updates["scenario"] = ScenarioName.CONTROLLED_INCREASE
        if "renewal" in lowered:
            updates["segment"] = Segment.RENEWAL
        elif "new business" in lowered or "new-business" in lowered:
            updates["segment"] = Segment.NEW_BUSINESS
        if any(term in lowered for term in ("last 12 months", "last twelve months", "12-month")):
            updates.update(
                {
                    "analysis_start_month": date(2025, 1, 1),
                    "analysis_end_month": date(2025, 12, 1),
                }
            )
        elif any(term in lowered for term in ("last 6 months", "last six months", "6-month")):
            updates.update(
                {
                    "analysis_start_month": date(2025, 7, 1),
                    "analysis_end_month": date(2025, 12, 1),
                }
            )
        elif context.analysis_start_month is None or context.analysis_end_month is None:
            updates.update(
                {
                    "analysis_start_month": date(2025, 1, 1),
                    "analysis_end_month": date(2025, 12, 1),
                }
            )
        return context.model_copy(update=updates)
