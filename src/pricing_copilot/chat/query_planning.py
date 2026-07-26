"""Deterministic intent classification, minimal tool selection, and visible query plans."""

from __future__ import annotations

from pricing_copilot.chat.contracts import (
    AnalyticsSource,
    ChatToolName,
    ConversationDecision,
    ConversationIntent,
    ConversationRoute,
    PlannedToolCall,
    StructuredQueryPlan,
)
from pricing_copilot.contracts import ScenarioName

_SOURCE_TERMS: tuple[tuple[AnalyticsSource, tuple[str, ...]], ...] = (
    (AnalyticsSource.CLAIMS, ("claims", "loss ratio", "loss-ratio", "claim severity", "frequency")),
    (AnalyticsSource.CONVERSION, ("conversion", "quote-to-sale", "renewal retention")),
    (AnalyticsSource.COMPETITORS, ("competitor", "price index")),
    (AnalyticsSource.PRICING_HISTORY, ("pricing history", "previous pricing", "previous action")),
    (
        AnalyticsSource.MARKET_INTELLIGENCE,
        (
            "market intelligence",
            "repair cost",
            "repair-cost",
            "regulatory",
            "weather",
            "theft",
            "economic commentary",
            "competitor announcement",
            "competitor announced",
            "announcement published",
        ),
    ),
    (
        AnalyticsSource.CUSTOMER_FEEDBACK,
        (
            "customer feedback",
            "customer channel",
            "customer channels",
            "attrition",
            "cancellation",
            "affordability",
            "fairness",
            "price sensitivity",
            "price concern",
            "comparison shopping",
            "call-centre",
            "call center",
            "complaint",
            "survey",
        ),
    ),
)
_CATEGORY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claims_cost", ("repair cost", "repair-cost", "parts", "labour")),
    ("competitor", ("competitor announcement", "competitor")),
    ("regulation", ("regulatory", "regulation")),
    ("claims_risk", ("weather", "theft")),
    ("affordability", ("affordability",)),
    (
        "customer_feedback",
        ("customer feedback", "complaint", "survey", "call-centre", "call center", "cancellation"),
    ),
)
_RECOMMENDATION_TERMS = (
    "recommend",
    "recommendation",
    "should we increase",
    "should we decrease",
    "what pricing decision",
)
_INVESTIGATION_TERMS = ("investigate", "investigation", "driver", "why did", "root cause")
_TREND_TERMS = ("trend", "over time", "movement", "change", "compare")

_SOURCE_REASONS: dict[AnalyticsSource, str] = {
    AnalyticsSource.CLAIMS: (
        "Needed for the requested claims metric or claims-performance question."
    ),
    AnalyticsSource.CONVERSION: "Needed for the requested conversion or renewal-retention metric.",
    AnalyticsSource.COMPETITORS: "Needed for the requested competitor-price evidence.",
    AnalyticsSource.PRICING_HISTORY: "Needed for the requested prior pricing action or outcome.",
    AnalyticsSource.MARKET_INTELLIGENCE: (
        "Needed for the requested external market-document evidence."
    ),
    AnalyticsSource.CUSTOMER_FEEDBACK: (
        "Needed for the requested aggregate customer-feedback evidence."
    ),
}


def _contains_any(message: str, terms: tuple[str, ...]) -> bool:
    return any(term in message for term in terms)


def _deduplicated_sources(message: str, decision: ConversationDecision) -> list[AnalyticsSource]:
    if "competitor" in message and any(
        term in message for term in ("announced", "announcement", "published", "source")
    ):
        return [AnalyticsSource.MARKET_INTELLIGENCE]
    inferred = [source for source, terms in _SOURCE_TERMS if _contains_any(message, terms)]
    # Use model-selected sources only when the request has no explicit source signal.
    # This prevents a broad model plan from expanding a narrow customer-document question.
    return list(dict.fromkeys(inferred or decision.sources))


def _sub_questions(message: str, sources: list[AnalyticsSource]) -> list[str]:
    questions: list[str] = []
    if AnalyticsSource.CUSTOMER_FEEDBACK in sources:
        if _contains_any(message, ("attrition", "cancellation", "retention risk")):
            questions.append(
                "What customer-feedback evidence indicates price-related attrition risk?"
            )
        if _contains_any(message, ("channel", "channels")):
            questions.append("Which customer-feedback channels support the conclusion?")
        if _contains_any(message, ("price sensitivity", "common pattern", "pattern")):
            questions.append("What common price-sensitivity pattern appears across the feedback?")
        if _contains_any(message, ("affordability", "fairness")):
            questions.append(
                "Does the scoped feedback show a material affordability or fairness concern?"
            )
    if AnalyticsSource.CONVERSION in sources:
        questions.append("What do the requested conversion or renewal-retention metrics show?")
    if AnalyticsSource.CLAIMS in sources:
        questions.append("What do the requested claims metrics show?")
    if AnalyticsSource.COMPETITORS in sources:
        questions.append("What do the requested competitor-price metrics show?")
    if AnalyticsSource.PRICING_HISTORY in sources:
        questions.append("What does the requested pricing-history evidence show?")
    if AnalyticsSource.MARKET_INTELLIGENCE in sources:
        if "competitor" in message and any(
            term in message for term in ("announced", "announcement", "published")
        ):
            questions.append(
                "Which competitor announced a pricing change, what was the change, and when "
                "was it published?"
            )
        else:
            questions.append("What do the requested market-intelligence documents show?")
    if _contains_any(message, _INVESTIGATION_TERMS) or _contains_any(
        message, ("should follow", "next investigation")
    ):
        questions.append("What investigation or limitation follows from the available evidence?")
    return list(dict.fromkeys(questions)) or ["Answer the user's requested evidence question."]


def _structured_plan(
    message: str,
    intent: ConversationIntent,
    sources: list[AnalyticsSource],
    *,
    recommendation: bool = False,
) -> StructuredQueryPlan:
    questions = _sub_questions(message, sources)
    if recommendation:
        return StructuredQueryPlan(
            intent=intent,
            sub_questions=[
                "Produce a governed pricing recommendation from the required portfolio evidence."
            ],
            required_filters=["portfolio scope", "analysis period", "scenario"],
            answer_sections=["Direct answer", "Key evidence", "Recommended action", "Citations"],
            evidence_rule=(
                "The governed workflow determines the required sources and validates the "
                "recommendation."
            ),
        )
    filters = ["scenario", "product", "region", "segment"]
    if any(
        source in {AnalyticsSource.MARKET_INTELLIGENCE, AnalyticsSource.CUSTOMER_FEEDBACK}
        for source in sources
    ):
        filters.extend(["document source", "metadata category when relevant"])
    return StructuredQueryPlan(
        intent=intent,
        sub_questions=questions,
        tool_calls=[
            PlannedToolCall(
                source=source,
                reason=_SOURCE_REASONS[source],
                supports_questions=questions,
            )
            for source in sources
        ],
        required_filters=filters,
        answer_sections=[
            "Direct answer",
            "Supporting evidence",
            "Investigation or limitation",
            "Citations",
        ],
        evidence_rule=(
            "Every material conclusion must cite retrieved evidence. "
            "A selected tool must support a cited conclusion or be excluded from the final answer."
        ),
    )


def plan_request(message: str, decision: ConversationDecision) -> ConversationDecision:
    """Constrain model output to a minimal, inspectable, source-aware execution plan."""
    lowered = message.lower()
    inferred_scenario = decision.scenario
    if _contains_any(lowered, ("controlled increase", "controlled-increase")):
        inferred_scenario = ScenarioName.CONTROLLED_INCREASE
    elif _contains_any(
        lowered,
        ("attrition", "price sensitivity", "retention risk", "retention concern"),
    ):
        inferred_scenario = ScenarioName.RETENTION_CONCERN
    inferred_sources = _deduplicated_sources(lowered, decision)
    # The chat surface always supplies a governed portfolio context.  When the user
    # explicitly names a source, do not let an over-cautious model ask them to repeat
    # that context instead of retrieving the scoped evidence.
    if decision.route is ConversationRoute.CLARIFY and inferred_sources:
        decision = decision.model_copy(
            update={
                "route": ConversationRoute.TOOL_CALL,
                "tool_name": ChatToolName.DOCUMENTS,
                "clarification_question": None,
                "suggested_next_steps": [],
            }
        )
    if decision.route is not ConversationRoute.TOOL_CALL:
        intent = decision.intent or ConversationIntent.DATA_LOOKUP
        return decision.model_copy(
            update={"intent": intent, "structured_plan": _structured_plan(lowered, intent, [])}
        )
    if decision.tool_name in {
        ChatToolName.READ_ONLY_SQL,
        ChatToolName.REPLAY,
        ChatToolName.EVALUATION,
        ChatToolName.DRIFT,
        ChatToolName.SCHEMA,
    }:
        return decision.model_copy(
            update={
                "intent": ConversationIntent.DATA_LOOKUP,
                "structured_plan": _structured_plan(lowered, ConversationIntent.DATA_LOOKUP, []),
            }
        )
    explicit_recommendation = any(term in lowered for term in _RECOMMENDATION_TERMS) or (
        "pricing action" in lowered and "pricing actions" not in lowered
    )
    if explicit_recommendation:
        return decision.model_copy(
            update={
                "intent": ConversationIntent.PRICING_RECOMMENDATION,
                "tool_name": ChatToolName.RECOMMENDATION,
                "sources": [],
                "document_categories": [],
                "structured_plan": _structured_plan(
                    lowered, ConversationIntent.PRICING_RECOMMENDATION, [], recommendation=True
                ),
            }
        )
    sources = inferred_sources
    categories = [category for category, terms in _CATEGORY_TERMS if _contains_any(lowered, terms)]
    document_sources = [
        source
        for source in sources
        if source in {AnalyticsSource.MARKET_INTELLIGENCE, AnalyticsSource.CUSTOMER_FEEDBACK}
    ]
    structured_sources = [source for source in sources if source not in document_sources]
    if document_sources and not structured_sources:
        intent = ConversationIntent.DOCUMENT_RETRIEVAL
        tool_name = ChatToolName.DOCUMENTS
    elif document_sources and structured_sources:
        intent = ConversationIntent.INVESTIGATION
        tool_name = ChatToolName.MULTI_SOURCE
    else:
        intent = (
            ConversationIntent.INVESTIGATION
            if _contains_any(lowered, _INVESTIGATION_TERMS)
            else ConversationIntent.TREND_ANALYSIS
            if _contains_any(lowered, _TREND_TERMS)
            else ConversationIntent.DATA_LOOKUP
        )
        tool_name = ChatToolName.ANALYTICS
    return decision.model_copy(
        update={
            "intent": intent,
            "tool_name": tool_name,
            "sources": sources,
            "document_query": message if document_sources else decision.document_query,
            "document_categories": categories if document_sources else [],
            "scenario": inferred_scenario,
            "structured_plan": _structured_plan(lowered, intent, sources),
        }
    )
