"""Single integration surface over every governed pricing-copilot capability.

`ChatToolFacade` is the ONE class the conversation agent imports. It composes the
existing subsystems (analytics database, document retrieval, replay, evaluation,
drift, and the governed workflow) without duplicating any business logic, and it
normalizes every answer into a JSON-serializable envelope:

    {"status", "source", "data", "citations", "error"}

`status` is one of the literal strings ``"ok"``, ``"not_found"``, ``"blocked"``.
Only known *operational* outcomes are converted into structured envelopes; real
programming errors are allowed to propagate uncaught.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Literal

from pricing_copilot.chat.contracts import ActivityStatus, ChatActivity
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    PortfolioQuestion,
    Region,
    ScenarioName,
    WorkflowResult,
)
from pricing_copilot.data.persistent import PersistentAnalyticsDatabase
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.drift.store import load_drift_report
from pricing_copilot.evaluation.store import load_benchmark_report
from pricing_copilot.governance.security import quarantine_unsafe_documents
from pricing_copilot.observability.contracts import TraceEvent, TraceEventKind
from pricing_copilot.replay.store import (
    ReplayArtifactIncompatibleError,
    ReplayArtifactMissingError,
    load_replay_artifact,
)
from pricing_copilot.workflow import run_portfolio_workflow

# The presentation listener the conversation agent supplies. Defined here (not
# imported from chat.service) so that module can later import ChatToolFacade
# without a circular import; both alias against the shared ChatActivity type.
ActivityListener = Callable[[ChatActivity], None]

Status = Literal["ok", "not_found", "blocked"]

# Human-readable labels for governed workflow activity. Kept in sync with the
# reference mapping in chat.service (ported, not imported).
CLAIMS_LABEL = "Getting information from claims performance data"
CONVERSION_LABEL = "Getting information from conversion performance data"
COMPETITOR_LABEL = "Getting information from competitor information data"
MARKET_INTELLIGENCE_LABEL = "Market intelligence gathering"
PRICING_HISTORY_LABEL = "Checking previous pricing actions"

_AGENT_LABELS: dict[str, str] = {
    "claims-specialist": CLAIMS_LABEL,
    "conversion-specialist": CONVERSION_LABEL,
    "market-intelligence-specialist": MARKET_INTELLIGENCE_LABEL,
    "pricing-history-specialist": PRICING_HISTORY_LABEL,
    "recommendation-agent": "Preparing a governed pricing recommendation",
    "governance-agent": "Checking recommendation governance",
    "portfolio-supervisor": "Supervisor coordinating specialist agents",
}
_PRESENTABLE_KINDS = {
    TraceEventKind.ROUTING,
    TraceEventKind.TOOL_CALL,
    TraceEventKind.MODEL_CALL,
    TraceEventKind.GUARDRAIL,
    TraceEventKind.FAILURE,
}
_STATUS_BY_TRACE: dict[str, ActivityStatus] = {
    "started": ActivityStatus.WORKING,
    "scheduled": ActivityStatus.SCHEDULED,
    "completed": ActivityStatus.COMPLETED,
    "blocked": ActivityStatus.BLOCKED,
    "failed": ActivityStatus.FAILED,
    "failed_safe": ActivityStatus.FAILED,
}


def _jsonable(value: object) -> object:
    """Coerce a single scalar to a JSON-serializable value.

    DuckDB free-form rows may carry ``datetime.date`` (the ``period`` column),
    which ``json.dumps`` cannot serialize as-is.
    """
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _serialize_rows(rows: list[tuple[object, ...]]) -> list[list[object]]:
    return [[_jsonable(cell) for cell in row] for row in rows]


def _envelope(
    status: Status,
    source: str,
    data: dict[str, object],
    citations: list[str],
    error: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "source": source,
        "data": data,
        "citations": citations,
        "error": error,
    }


class ChatToolFacade:
    """The single tool surface the conversation agent composes against.

    Every method returns a JSON-serializable ``dict[str, object]`` with exactly
    the keys ``status``, ``source``, ``data``, ``citations`` and ``error``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Analytics database                                                  #
    # ------------------------------------------------------------------ #
    def describe_analytics_schema(self) -> dict[str, object]:
        """Return the static, read-only analytics catalogue. Always ``"ok"``."""
        database = PersistentAnalyticsDatabase(self.settings.analytics_database_path)
        catalogue = database.schema_catalogue()
        return _envelope("ok", "analytics_database", dict(catalogue), [])

    def execute_read_only_sql(self, sql: str, scenario: ScenarioName) -> dict[str, object]:
        """Run a validated, scenario-scoped free-form SELECT over the analytics DB.

        A rejected (unsafe) query maps to ``"blocked"`` with the validator's
        reason; it never raises.
        """
        database = PersistentAnalyticsDatabase(self.settings.analytics_database_path)
        try:
            result = database.execute_freeform_sql(sql, scenario)
        except ValueError as exc:
            return _envelope("blocked", "analytics_database", {}, [], str(exc))
        data: dict[str, object] = {
            "sql": result.sql,
            "columns": list(result.columns),
            "rows": _serialize_rows(result.rows),
            "database_version": result.database_version,
        }
        return _envelope("ok", "analytics_database", data, [])

    # ------------------------------------------------------------------ #
    # Documents                                                           #
    # ------------------------------------------------------------------ #
    def search_documents(
        self,
        query: str,
        scenario: ScenarioName,
        region: Region,
        top_k: int = 6,
    ) -> dict[str, object]:
        """Retrieve corpus documents for the caller's query, quarantining unsafe ones.

        An empty result is still a valid ``"ok"`` answer.
        """
        retrieved = retrieve_documents(
            scenario=scenario, region=region, query=query, top_k=top_k
        )
        safe_documents, _ = quarantine_unsafe_documents(retrieved)
        documents: list[dict[str, object]] = [
            {
                "document_id": item.document.document_id,
                "title": item.document.title,
                "snippet": item.document.body,
                "source_type": item.document.source_type.value,
                "sentiment": item.document.sentiment.value,
                "score": item.score,
            }
            for item in safe_documents
        ]
        citations = [item.document.document_id for item in safe_documents]
        data: dict[str, object] = {"documents": documents, "count": len(documents)}
        return _envelope("ok", "document_corpus", data, citations)

    # ------------------------------------------------------------------ #
    # Replay                                                              #
    # ------------------------------------------------------------------ #
    def load_replay(self, scenario: ScenarioName) -> dict[str, object]:
        """Load a version-checked replay artifact for a scenario.

        A missing OR incompatible artifact both map to ``"not_found"`` - either
        way it must be re-recorded before it can be served.
        """
        try:
            artifact = load_replay_artifact(scenario, self.settings)
        except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
            return _envelope("not_found", "replay_artifact", {}, [], str(exc))
        workflow_result = artifact.chat_response.workflow_result
        data: dict[str, object] = {
            "recorded_at": artifact.recorded_at.isoformat(),
            "configuration_versions": artifact.configuration_versions.model_dump(mode="json"),
        }
        citations: list[str] = []
        if workflow_result is not None:
            data["workflow_result"] = workflow_result.model_dump(mode="json")
            citations = list(workflow_result.recommendation.cited_evidence_ids)
        return _envelope("ok", "replay_artifact", data, citations)

    # ------------------------------------------------------------------ #
    # Evaluation and drift                                                #
    # ------------------------------------------------------------------ #
    def load_evaluation(self) -> dict[str, object]:
        """Load the latest evaluation benchmark, or ``"not_found"`` if none exists."""
        report = load_benchmark_report(self.settings)
        if report is None:
            return _envelope(
                "not_found",
                "evaluation_report",
                {},
                [],
                "No evaluation benchmark has been recorded yet.",
            )
        return _envelope("ok", "evaluation_report", report.model_dump(mode="json"), [])

    def load_drift(self) -> dict[str, object]:
        """Load the latest drift monitoring report, or ``"not_found"`` if none exists."""
        report = load_drift_report(self.settings)
        if report is None:
            return _envelope(
                "not_found",
                "drift_report",
                {},
                [],
                "No drift monitoring run has been recorded yet.",
            )
        return _envelope("ok", "drift_report", report.model_dump(mode="json"), [])

    # ------------------------------------------------------------------ #
    # Governed recommendation                                             #
    # ------------------------------------------------------------------ #
    def run_recommendation(
        self,
        question: PortfolioQuestion,
        on_activity: ActivityListener | None = None,
    ) -> dict[str, object]:
        """Run the governed multi-agent workflow for a fully resolved question.

        Known operational failures (missing credentials, timeout, specialist
        crash, or governance rejection past the revision budget - all surfaced as
        a ``"workflow:"``-prefixed missing-evidence reason) map to ``"blocked"``.
        A legitimate business ``investigate`` decision is a normal ``"ok"`` result.
        An invalid ``PortfolioQuestion`` is a caller bug and is left to raise.
        """
        event_listener = self._build_event_listener(on_activity)
        result = run_portfolio_workflow(
            question, self.settings, event_listener=event_listener
        )
        operational_failure = next(
            (
                item.reason
                for item in result.missing_evidence
                if item.reason.startswith("workflow:")
            ),
            None,
        )
        if operational_failure is not None:
            return _envelope("blocked", result.source.value, {}, [], operational_failure)
        citations = self._collect_citations(result)
        return _envelope("ok", result.source.value, result.model_dump(mode="json"), citations)

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _collect_citations(result: WorkflowResult) -> list[str]:
        """Deduplicated union of the recommendation's and every specialist's evidence IDs."""
        seen: dict[str, None] = {}
        for evidence_id in result.recommendation.cited_evidence_ids:
            seen.setdefault(evidence_id, None)
        for report in result.specialist_reports:
            for evidence_id in report.evidence_ids:
                seen.setdefault(evidence_id, None)
        return list(seen)

    def _build_event_listener(
        self, on_activity: ActivityListener | None
    ) -> Callable[[TraceEvent], None] | None:
        if on_activity is None:
            return None

        def forward(event: TraceEvent) -> None:
            activity = self._activity_from_trace(event)
            if activity is not None:
                on_activity(activity)

        return forward

    @staticmethod
    def _activity_from_trace(event: TraceEvent) -> ChatActivity | None:
        """Translate a governed-workflow ``TraceEvent`` into a presentation ``ChatActivity``.

        Ported from ``chat.service._activity_from_trace`` (reference only). Non
        presentation-worthy events return ``None`` and are dropped.
        """
        if event.kind not in _PRESENTABLE_KINDS:
            return None
        label = _AGENT_LABELS.get(event.name)
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
        status = _STATUS_BY_TRACE.get(event.status, ActivityStatus.WORKING)
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
