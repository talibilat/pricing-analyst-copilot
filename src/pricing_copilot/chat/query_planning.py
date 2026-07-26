"""Deterministic intent classification, minimal tool selection, and visible query plans."""

from __future__ import annotations

from pricing_copilot.chat.contracts import (
    AnalysisQuestionType,
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
_RELIABILITY_TERMS = (
    "reliability",
    "conflicting",
    "conflict",
    "incomplete",
    "outdated",
    "stale",
    "data quality",
)
_ROOT_CAUSE_TERMS = (
    "root cause",
    "plausible cause",
    "most plausible",
    "unusual portfolio",
    "what caused",
)
_CUSTOMER_BEHAVIOR_TERMS = (
    "customer behaviour",
    "customer behavior",
    "customer expectation",
    "changing behaviour",
    "changing behavior",
)
_PREVIOUS_DECISION_TERMS = (
    "previous decision",
    "earlier pricing",
    "earlier action",
    "intended outcome",
    "what should be learned",
)
_GOVERNANCE_TERMS = (
    "governance",
    "escalat",
    "human specialist",
    "handle automatically",
    "human review",
)
_COUNTERFACTUAL_TERMS = ("counterfactual", "if no pricing action", "if no action")
_SEGMENTATION_TERMS = (
    "customer segment",
    "different profitability",
    "selection risk",
    "unfair customer",
    "differentiated pricing",
)

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


def _explicit_recommendation_requested(message: str) -> bool:
    negated_requests = (
        "without recommend",
        "do not recommend",
        "don't recommend",
        "no recommendation",
        "not asking for a recommendation",
        "if no pricing action",
        "if no action",
    )
    if _contains_any(message, negated_requests):
        return False
    return _contains_any(message, _RECOMMENDATION_TERMS) or (
        "pricing action" in message and "pricing actions" not in message
    )


def _deduplicated_sources(message: str, decision: ConversationDecision) -> list[AnalyticsSource]:
    if "competitor" in message and any(
        term in message for term in ("announced", "announcement", "published", "source")
    ):
        return [AnalyticsSource.MARKET_INTELLIGENCE]
    inferred = [source for source, terms in _SOURCE_TERMS if _contains_any(message, terms)]
    # Use model-selected sources only when the request has no explicit source signal.
    # This prevents a broad model plan from expanding a narrow customer-document question.
    return list(dict.fromkeys(inferred or decision.sources))


def _analysis_type(
    message: str, *, explicit_recommendation: bool
) -> AnalysisQuestionType:
    if _contains_any(message, _RELIABILITY_TERMS):
        return AnalysisQuestionType.RELIABILITY
    if _contains_any(message, _ROOT_CAUSE_TERMS):
        return AnalysisQuestionType.ROOT_CAUSE
    if _contains_any(message, _CUSTOMER_BEHAVIOR_TERMS):
        return AnalysisQuestionType.CUSTOMER_BEHAVIOR
    if _contains_any(message, _PREVIOUS_DECISION_TERMS):
        return AnalysisQuestionType.PREVIOUS_DECISIONS
    if _contains_any(message, _GOVERNANCE_TERMS):
        return AnalysisQuestionType.GOVERNANCE_ESCALATION
    if _contains_any(message, _COUNTERFACTUAL_TERMS):
        return AnalysisQuestionType.COUNTERFACTUAL
    if _contains_any(message, _SEGMENTATION_TERMS):
        return AnalysisQuestionType.SEGMENTATION
    if explicit_recommendation:
        return AnalysisQuestionType.RECOMMENDATION
    if _contains_any(message, _TREND_TERMS):
        return AnalysisQuestionType.TREND
    return AnalysisQuestionType.LOOKUP


def _sources_for_analysis_type(
    analysis_type: AnalysisQuestionType,
    inferred_sources: list[AnalyticsSource],
) -> list[AnalyticsSource]:
    broad_types = {
        AnalysisQuestionType.RELIABILITY,
        AnalysisQuestionType.ROOT_CAUSE,
        AnalysisQuestionType.GOVERNANCE_ESCALATION,
        AnalysisQuestionType.COUNTERFACTUAL,
        AnalysisQuestionType.SEGMENTATION,
    }
    if analysis_type in broad_types:
        return list(AnalyticsSource)
    if analysis_type is AnalysisQuestionType.CUSTOMER_BEHAVIOR:
        return [AnalyticsSource.CONVERSION, AnalyticsSource.CUSTOMER_FEEDBACK]
    if analysis_type is AnalysisQuestionType.PREVIOUS_DECISIONS:
        return [
            AnalyticsSource.PRICING_HISTORY,
            AnalyticsSource.CLAIMS,
            AnalyticsSource.CONVERSION,
        ]
    return inferred_sources


def _sub_questions(
    message: str,
    sources: list[AnalyticsSource],
    analysis_type: AnalysisQuestionType,
) -> list[str]:
    typed_questions: dict[AnalysisQuestionType, list[str]] = {
        AnalysisQuestionType.RELIABILITY: [
            "Which sources conflict with other evidence?",
            "Which sources are incomplete or outdated?",
            "How should those limitations change the conclusion?",
        ],
        AnalysisQuestionType.ROOT_CAUSE: [
            "What is the most unusual portfolio trend?",
            "What are the most plausible contributing factors?",
            "Which sources corroborate or contradict each explanation?",
        ],
        AnalysisQuestionType.CUSTOMER_BEHAVIOR: [
            "What patterns appear in aggregate customer feedback?",
            "What patterns appear in conversion and retention?",
            "What combined behavioral interpretation is supported?",
        ],
        AnalysisQuestionType.PREVIOUS_DECISIONS: [
            "Which earlier pricing actions and outcomes are recorded?",
            "Which actions coincided with the intended outcome, and which did not?",
            "What lessons are supported for future decisions?",
        ],
        AnalysisQuestionType.GOVERNANCE_ESCALATION: [
            "Which findings can be calculated or flagged automatically?",
            "Which findings require a human specialist before a decision?",
            "What evidence or governance rule explains each escalation?",
        ],
        AnalysisQuestionType.COUNTERFACTUAL: [
            "What is the likely direction of profitability if no action is taken?",
            "What is the likely direction of retention and market position?",
            "Which assumptions and uncertainties constrain the counterfactual?",
        ],
        AnalysisQuestionType.SEGMENTATION: [
            "What evidence supports materially different segment treatment?",
            "How should unfair outcomes and selection risk be controlled?",
            "Which evidence gaps prevent a supported differentiated action?",
        ],
        AnalysisQuestionType.RECOMMENDATION: [
            "What governed pricing action is supported by the complete evidence?",
        ],
    }
    if analysis_type in typed_questions:
        return typed_questions[analysis_type]
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
    unique_questions = list(dict.fromkeys(questions))
    # StructuredQueryPlan intentionally exposes at most five questions.  A broad
    # model-selected source list can otherwise yield one question per source plus
    # an investigation question, exceeding the contract before it reaches the UI.
    return unique_questions[:5] or ["Answer the user's requested evidence question."]


def _questions_supported_by(source: AnalyticsSource, questions: list[str]) -> list[str]:
    """Associate a tool with the question it can answer, not the entire plan."""
    terms_by_source: dict[AnalyticsSource, tuple[str, ...]] = {
        AnalyticsSource.CLAIMS: ("claims",),
        AnalyticsSource.CONVERSION: ("conversion", "renewal-retention"),
        AnalyticsSource.COMPETITORS: ("competitor",),
        AnalyticsSource.PRICING_HISTORY: ("pricing-history",),
        AnalyticsSource.MARKET_INTELLIGENCE: ("market-intelligence", "competitor announced"),
        AnalyticsSource.CUSTOMER_FEEDBACK: ("customer-feedback", "attrition", "affordability"),
    }
    supported = [
        question
        for question in questions
        if any(term in question.lower() for term in terms_by_source[source])
    ]
    return supported or ["Provide scoped evidence for the final synthesis."]


def _structured_plan(
    message: str,
    intent: ConversationIntent,
    sources: list[AnalyticsSource],
    *,
    analysis_type: AnalysisQuestionType,
    recommendation: bool = False,
) -> StructuredQueryPlan:
    questions = _sub_questions(message, sources, analysis_type)
    if recommendation:
        return StructuredQueryPlan(
            intent=intent,
            analysis_type=analysis_type,
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
        analysis_type=analysis_type,
        sub_questions=questions,
        tool_calls=[
            PlannedToolCall(
                source=source,
                reason=_SOURCE_REASONS[source],
                supports_questions=_questions_supported_by(source, questions),
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
    explicit_recommendation = _explicit_recommendation_requested(lowered)
    analysis_type = _analysis_type(
        lowered, explicit_recommendation=explicit_recommendation
    )
    inferred_sources = _sources_for_analysis_type(analysis_type, inferred_sources)
    evidence_workflow_types = {
        AnalysisQuestionType.RELIABILITY,
        AnalysisQuestionType.ROOT_CAUSE,
        AnalysisQuestionType.CUSTOMER_BEHAVIOR,
        AnalysisQuestionType.PREVIOUS_DECISIONS,
        AnalysisQuestionType.GOVERNANCE_ESCALATION,
        AnalysisQuestionType.COUNTERFACTUAL,
        AnalysisQuestionType.SEGMENTATION,
    }
    if (
        decision.route is not ConversationRoute.TOOL_CALL
        and analysis_type in evidence_workflow_types
    ):
        document_sources = [
            source
            for source in inferred_sources
            if source
            in {AnalyticsSource.MARKET_INTELLIGENCE, AnalyticsSource.CUSTOMER_FEEDBACK}
        ]
        structured_sources = [
            source for source in inferred_sources if source not in document_sources
        ]
        decision = decision.model_copy(
            update={
                "route": ConversationRoute.TOOL_CALL,
                "tool_name": (
                    ChatToolName.MULTI_SOURCE
                    if document_sources and structured_sources
                    else ChatToolName.DOCUMENTS
                    if document_sources
                    else ChatToolName.ANALYTICS
                ),
                "response": None,
                "clarification_question": None,
                "suggested_next_steps": [],
            }
        )
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
            update={
                "intent": (
                    ConversationIntent.PRICING_RECOMMENDATION
                    if explicit_recommendation
                    else intent
                ),
                "tool_name": (
                    ChatToolName.RECOMMENDATION if explicit_recommendation else decision.tool_name
                ),
                "structured_plan": _structured_plan(
                    lowered,
                    (
                        ConversationIntent.PRICING_RECOMMENDATION
                        if explicit_recommendation
                        else intent
                    ),
                    [],
                    analysis_type=analysis_type,
                    recommendation=explicit_recommendation,
                ),
            }
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
                "structured_plan": _structured_plan(
                    lowered,
                    ConversationIntent.DATA_LOOKUP,
                    [],
                    analysis_type=analysis_type,
                ),
            }
        )
    if (
        decision.tool_name is ChatToolName.RECOMMENDATION
        and decision.intent is ConversationIntent.PRICING_RECOMMENDATION
    ):
        return decision.model_copy(
            update={
                "intent": ConversationIntent.PRICING_RECOMMENDATION,
                "sources": [],
                "document_categories": [],
                "structured_plan": _structured_plan(
                    lowered,
                    ConversationIntent.PRICING_RECOMMENDATION,
                    [],
                    analysis_type=AnalysisQuestionType.RECOMMENDATION,
                    recommendation=True,
                ),
            }
        )
    if explicit_recommendation:
        return decision.model_copy(
            update={
                "intent": ConversationIntent.PRICING_RECOMMENDATION,
                "tool_name": ChatToolName.RECOMMENDATION,
                "sources": [],
                "document_categories": [],
                "structured_plan": _structured_plan(
                    lowered,
                    ConversationIntent.PRICING_RECOMMENDATION,
                    [],
                    analysis_type=AnalysisQuestionType.RECOMMENDATION,
                    recommendation=True,
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
            if analysis_type
            in {
                AnalysisQuestionType.RELIABILITY,
                AnalysisQuestionType.ROOT_CAUSE,
                AnalysisQuestionType.CUSTOMER_BEHAVIOR,
                AnalysisQuestionType.PREVIOUS_DECISIONS,
                AnalysisQuestionType.GOVERNANCE_ESCALATION,
                AnalysisQuestionType.COUNTERFACTUAL,
                AnalysisQuestionType.SEGMENTATION,
            }
            or _contains_any(lowered, _INVESTIGATION_TERMS)
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
            "structured_plan": _structured_plan(
                lowered, intent, sources, analysis_type=analysis_type
            ),
        }
    )
