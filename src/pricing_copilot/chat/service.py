"""Safe, typed chat routing over permitted portfolio-level sources."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from time import monotonic

from pricing_copilot.catalog import SUPPORTED_PORTFOLIOS, UnsupportedPortfolioError
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
from pricing_copilot.chat.tool_registry import coordinator_catalogue
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


def _portfolio_label(product: Product, region: Region, segment: Segment) -> str:
    return " ".join(
        value.replace("_", " ") for value in (region.value, product.value, segment.value)
    )


class DefaultConversationTools:
    """Adapts the existing governed capabilities to the conversation graph."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = PersistentAnalyticsDatabase(self.settings.analytics_database_path)

    def available_tools(self) -> dict[str, object]:
        return coordinator_catalogue()

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
                query=message,
            )
        if decision.tool_name is ChatToolName.DOCUMENTS:
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
                query=decision.document_query or message,
                document_categories=decision.document_categories,
            )
        if decision.tool_name is ChatToolName.MULTI_SOURCE:
            selected_sources = [source.value for source in decision.sources]
            return self._retrieve_sources(
                selected_sources,
                decision.requested_fields,
                context,
                listener,
                query=decision.document_query or message,
                document_categories=decision.document_categories,
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
            if sources:
                return self._retrieve_sources(
                    sources,
                    decision.requested_fields,
                    context,
                    listener,
                    query=message,
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
        asks_for_names = any(
            phrase in lowered
            for phrase in (
                "competitor names",
                "names of competitors",
                "unique competitors",
                "distinct competitors",
            )
        )
        document_request = any(
            term in lowered
            for term in ("announced", "announcement", "published", "source", "document")
        )
        return "competitor" in lowered and asks_for_names and not document_request

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
                ", ".join(names[:-1]) + f", and {names[-1]}" if len(names) > 1 else names[0]
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
        *,
        query: str,
        document_categories: list[str] | None = None,
    ) -> ChatResponse:
        if (
            context.segment
            and (context.product, context.region, context.segment) not in SUPPORTED_PORTFOLIOS
        ):
            return self._unsupported_portfolio_response(context, context.segment)
        activities: list[ChatActivity] = []
        tables: list[ChatTable] = []
        evidence_ids: list[str] = []
        limitations: list[str] = []
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
                table, document_ids, document_limitations = self._retrieve_documents(
                    source, context, query, document_categories or []
                )
                evidence_ids.extend(document_ids)
                limitations.extend(document_limitations)
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
            if evidence_ids:
                message = self._compose_retrieval_response(
                    query=query,
                    source_names=source_names,
                    evidence_count=len(evidence_ids),
                    tables=tables,
                )
            elif any(
                source in {"market_intelligence", "customer_feedback"} for source in source_list
            ):
                message = (
                    f"Insufficient evidence: no safe document matched the requested scope in "
                    f"{source_names}. I have not inferred a conclusion."
                )
            else:
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
            limitations=limitations,
        )

    def _compose_retrieval_response(
        self,
        *,
        query: str,
        source_names: str,
        evidence_count: int,
        tables: list[ChatTable],
    ) -> str:
        """Compose a direct, bounded answer from retrieved evidence.

        Raw chunks remain in the supporting-data expander.  This method is deliberately
        separate so that a chat answer states a conclusion, explains its evidence, and
        preserves citations without turning the answer into a retrieval dump.
        """
        evidence = self._document_evidence_rows(tables)
        lowered = query.lower()
        customer = [item for item in evidence if item["table"] == "Customer Feedback"]
        market = [item for item in evidence if item["table"] == "Market Intelligence"]
        facts = self._feedback_facts(customer)
        citations = self._citation_lines(evidence)

        if (
            market
            and "competitor" in lowered
            and any(term in lowered for term in ("announced", "announcement", "published"))
        ):
            direct, limitation = self._competitor_announcement_conclusion(market)
        elif (
            customer
            and ("affordability" in lowered or "fairness" in lowered)
            and any(term in lowered for term in ("does", "is there", "show a material", "material"))
        ):
            direct = self._controlled_feedback_conclusion(facts)
            limitation = (
                "This is a conclusion about the available aggregate, scoped feedback corpus. "
                "It does not measure individual customers or prove future price acceptance."
            )
        elif customer and any(
            term in lowered
            for term in ("attrition", "cancellation", "retention risk", "retention concern")
        ):
            direct = self._attrition_conclusion(facts)
            limitation = (
                "The evidence is aggregate and observational, so it identifies a retention "
                "risk but cannot quantify price elasticity or prove causality. A retention and "
                "price-elasticity investigation should follow before any further increase is "
                "considered."
            )
        elif customer and any(
            term in lowered
            for term in ("price sensitivity", "customer channel", "customer channels")
        ):
            direct = self._price_sensitivity_conclusion(facts)
            limitation = (
                "The common pattern is evidence of price sensitivity, not proof that every "
                "customer will reject another increase. Validate it with aggregate retention "
                "and elasticity monitoring before changing price."
            )
        else:
            direct = (
                f"The retrieved evidence directly addresses the requested question from "
                f"{source_names}. It supports the findings listed below."
            )
            limitation = (
                "The answer is limited to the retrieved, scoped evidence. "
                "No recommendation is implied unless one was explicitly requested."
            )
        supporting = self._supporting_evidence_lines(evidence)
        no_summary = (
            f"Retrieved {evidence_count} evidence item(s), but no safe summary could be composed."
        )
        return (
            "## Direct answer\n"
            f"{direct}\n\n"
            "## Supporting evidence\n"
            f"{supporting or no_summary}\n\n"
            "## Investigation or limitation\n"
            f"{limitation}\n\n"
            "## Citations\n"
            f"{citations}"
        )

    @staticmethod
    def _document_evidence_rows(tables: list[ChatTable]) -> list[dict[str, str]]:
        """Return citation-ready rows while retaining document metadata for composition."""
        evidence: list[dict[str, str]] = []
        for table in tables:
            if "relevant_text" not in table.columns:
                continue
            document_id_index = table.columns.index("document_id")
            chunk_id_index = table.columns.index("chunk_id")
            text_index = table.columns.index("relevant_text")
            source_index = table.columns.index("source")
            date_index = table.columns.index("source_date")
            score_index = table.columns.index("retrieval_score")
            for row in table.rows[:3]:
                document_id = row[document_id_index]
                chunk_id = row[chunk_id_index]
                text = row[text_index]
                if isinstance(document_id, str) and isinstance(text, str):
                    evidence_id = chunk_id if isinstance(chunk_id, str) else document_id
                    evidence.append(
                        {
                            "table": table.title,
                            "evidence_id": evidence_id,
                            "text": text,
                            "source": str(row[source_index]),
                            "source_date": str(row[date_index]),
                            "score": str(row[score_index]),
                        }
                    )
        return evidence

    @staticmethod
    def _feedback_facts(evidence: list[dict[str, str]]) -> set[str]:
        text = " ".join(item["text"].lower() for item in evidence)
        facts: set[str] = set()
        if "cancellation" in text and "price" in text:
            facts.add("price-related cancellations")
        if "affordability" in text:
            facts.add("affordability concerns")
        if "comparison shopping" in text or "shopping around" in text:
            facts.add("comparison shopping")
        if "small minority" in text or "price-related comments remain a small minority" in text:
            facts.add("price comments are a small minority")
        if "no concentrated" in text or "no recurring" in text:
            facts.add("no recurring affordability or fairness theme")
        if "claims handling" in text or "communication" in text or "documentation" in text:
            facts.add("other service themes dominate")
        return facts

    @staticmethod
    def _competitor_announcement_conclusion(evidence: list[dict[str, str]]) -> tuple[str, str]:
        text = " ".join(item["text"] for item in evidence)
        match = re.search(r"competitor\s+([A-Z][A-Za-z ]+?)\s+announced\s+(.+?)(?:\.|$)", text)
        if match is None:
            return (
                "Insufficient evidence: the retrieved document does not identify a competitor "
                "announcement and change.",
                "The source could not support all requested details, so no pricing conclusion "
                "is drawn.",
            )
        competitor, change = (part.strip() for part in match.groups())
        publication_date = evidence[0]["source_date"]
        return (
            f"{competitor} announced {change}; the announcement was published on "
            f"{publication_date}. However, the source does not state the direction or magnitude "
            "of the repricing, so the evidence is insufficient to identify the exact pricing "
            "change.",
            "Treat this as external market evidence for Aviva. Do not infer a specific competitor "
            "price movement without a source that states it.",
        )

    @staticmethod
    def _attrition_conclusion(facts: set[str]) -> str:
        indicators = [
            phrase
            for phrase in (
                "price-related cancellations",
                "affordability concerns",
                "comparison shopping",
            )
            if phrase in facts
        ]
        if len(indicators) >= 2:
            return (
                "Renewal pricing appears to be contributing to attrition through "
                f"{_format_list(indicators)}."
            )
        return (
            "The retrieved customer feedback indicates a possible price-related attrition risk, "
            "but the available evidence is incomplete."
        )

    @staticmethod
    def _price_sensitivity_conclusion(facts: set[str]) -> str:
        channels: list[str] = []
        if "price-related cancellations" in facts:
            channels.append("cancellation records")
        if "affordability concerns" in facts:
            channels.append("affordability feedback")
        if "comparison shopping" in facts:
            channels.append("call-centre conversations")
        if len(channels) >= 2:
            return (
                f"{_format_list(channels).capitalize()} consistently indicate price sensitivity. "
                "The common pattern is repeated price concern, comparison shopping, and evidence "
                "that customers may not absorb another increase."
            )
        return (
            "The retrieved feedback suggests price sensitivity, but it does not cover enough "
            "channels for a firm conclusion."
        )

    @staticmethod
    def _controlled_feedback_conclusion(facts: set[str]) -> str:
        if {
            "price comments are a small minority",
            "no recurring affordability or fairness theme",
        }.issubset(facts):
            suffix = (
                " Most feedback instead concerns claims handling, communication, documentation, "
                "or claims status."
                if "other service themes dominate" in facts
                else ""
            )
            return (
                "No material affordability or fairness concern is evidenced in the "
                "controlled-increase scenario. Price-related comments are a small minority, "
                "with no recurring affordability theme "
                f"and no concentrated fairness concern.{suffix}"
            )
        return (
            "The retrieved controlled-increase feedback does not provide enough evidence to "
            "confirm "
            "or rule out a material affordability or fairness concern."
        )

    @staticmethod
    def _supporting_evidence_lines(evidence: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for item in evidence:
            excerpt = " ".join(item["text"].split())
            # Evidence documents may start with Markdown headings.  A chat bullet is
            # prose, so remove heading syntax before Streamlit renders the response.
            excerpt = re.sub(r"#+\s*", "", excerpt).strip()
            if len(excerpt) > 280:
                excerpt = f"{excerpt[:277].rstrip()}..."
            lines.append(f"- {excerpt} [{item['evidence_id']}]")
        return "\n".join(lines)

    @staticmethod
    def _citation_lines(evidence: list[dict[str, str]]) -> str:
        return "\n".join(
            f"- [{item['evidence_id']}] {item['source']} - {item['source_date']}; "
            f"retrieval score {item['score']}"
            for item in evidence
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

    def _retrieve_documents(
        self, source: str, context: ChatContext, query: str, categories: list[str]
    ) -> tuple[ChatTable, list[str], list[str]]:
        retrieved = retrieve_documents(
            scenario=context.scenario,
            region=context.region,
            product=context.product,
            segment=context.segment or Segment.RENEWAL,
            query=query,
            top_k=12,
            settings=self.settings,
            categories=categories,
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
                document.chunk_id,
                document.source,
                (
                    document.retrieval_score
                    if document.retrieval_score is not None
                    else document.score
                ),
                document.document.sentiment.value,
                document.document.body,
            ]
            for document in selected
        ]
        return (
            ChatTable(
                title=(
                    "Customer Feedback" if source == "customer_feedback" else "Market Intelligence"
                ),
                columns=[
                    "document_id",
                    "source_type",
                    "title",
                    "source_date",
                    "chunk_id",
                    "source",
                    "retrieval_score",
                    "sentiment",
                    "relevant_text",
                ],
                rows=rows,
            ),
            [document.evidence_id for document in selected],
            (
                []
                if selected
                else ["No document matched the requested source and metadata filters."]
            ),
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
        if (context.product, context.region, selected_segment) not in SUPPORTED_PORTFOLIOS:
            return self._unsupported_portfolio_response(context, selected_segment)
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
        workflow_started = monotonic()
        self._emit(
            ChatActivity(
                status=ActivityStatus.WORKING,
                label="Portfolio analysis workflow",
                purpose="Combining the requested portfolio evidence into an analyst answer.",
                source="portfolio_analysis",
            ),
            activities,
            listener,
        )
        try:
            if decision.tool_name is ChatToolName.RECOMMENDATION:
                result = run_portfolio_workflow(
                    question, self.settings, event_listener=record_trace_event
                )
            else:
                result = run_baseline_portfolio_workflow(
                    question, self.settings, FakeRecommendationSynthesizer()
                )
        except UnsupportedPortfolioError:
            return self._unsupported_portfolio_response(context, selected_segment)
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label="Portfolio analysis workflow",
                purpose="Combined the requested portfolio evidence into an analyst answer.",
                source="portfolio_analysis",
                duration_ms=(monotonic() - workflow_started) * 1_000,
            ),
            activities,
            listener,
        )
        if result.analytics is None or any(
            item.reason.startswith("workflow:") for item in result.missing_evidence
        ):
            # A specialist-runtime failure must not hide the useful deterministic evidence.
            # The response composer reports the reduced confidence and outstanding limitations.
            try:
                result = run_baseline_portfolio_workflow(
                    question, self.settings, FakeRecommendationSynthesizer()
                )
            except UnsupportedPortfolioError:
                return self._unsupported_portfolio_response(context, selected_segment)
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
    def _unsupported_portfolio_response(context: ChatContext, segment: Segment) -> ChatResponse:
        supported_scopes = _format_list(
            sorted(
                _portfolio_label(product, region, supported_segment)
                for product, region, supported_segment in SUPPORTED_PORTFOLIOS
            )
        )
        requested_scope = _portfolio_label(context.product, context.region, segment)
        return ChatResponse(
            intent=ChatIntent.UNSUPPORTED,
            context=context.model_copy(update={"segment": segment}),
            message=(
                f"I do not have data for {requested_scope}. "
                f"This workspace currently supports {supported_scopes}. "
                "Choose the supported segment to continue, or add data for the requested segment."
            ),
            limitations=["The requested portfolio segment is not available in this workspace."],
            suggested_next_steps=[
                "Show claims and conversion performance for renewal.",
            ],
            requires_clarification=True,
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
        source_by_name = {
            "claims-specialist": "claims",
            "conversion-specialist": "conversion",
            "market-intelligence-specialist": "market_intelligence",
            "pricing-history-specialist": "pricing_history",
            "recommendation-agent": "recommendation",
            "governance-agent": "governance",
            "portfolio-supervisor": "portfolio_analysis",
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
        source = source_by_name.get(event.name)
        if source is None and event.kind is TraceEventKind.TOOL_CALL:
            name = event.name.lower()
            source = next(
                (
                    candidate
                    for term, candidate in (
                        ("claim", "claims"),
                        ("conversion", "conversion"),
                        ("competitor", "competitors"),
                        ("pricing", "pricing_history"),
                        ("document", "market_intelligence"),
                        ("market", "market_intelligence"),
                    )
                    if term in name
                ),
                None,
            )
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
            source=source,
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
        if "retention concern" in lowered or "retention risk" in lowered:
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
