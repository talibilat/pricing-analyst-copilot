from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

import pytest

from pricing_copilot.chat.contracts import (
    AnalysisQuestionType,
    AnalyticsSource,
    ChatIntent,
    ChatToolName,
    ConversationDecision,
    ConversationIntent,
    ConversationMessage,
    ConversationRoute,
)
from pricing_copilot.chat.query_planning import plan_request
from pricing_copilot.chat.service import ChatService
from pricing_copilot.config import Settings
from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument


class BroadDocumentPlanner:
    """Simulates an over-broad model plan that must be constrained before execution."""

    def plan(
        self,
        message: str,
        history: Sequence[ConversationMessage],
        available_tools: dict[str, object],
        context: object,
    ) -> ConversationDecision:
        assert "data_sources" in available_tools
        return ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.RECOMMENDATION,
            sources=[AnalyticsSource.CLAIMS, AnalyticsSource.MARKET_INTELLIGENCE],
        )


def _service(tmp_path: Path) -> ChatService:
    return ChatService(
        Settings(analytics_database_path=tmp_path / "analytics.duckdb"),
        planner=BroadDocumentPlanner(),
    )


def test_explicit_customer_feedback_question_does_not_repeat_known_scope() -> None:
    decision = ConversationDecision(
        route=ConversationRoute.CLARIFY,
        clarification_question="Which personal motor segment and region should I use?",
    )

    planned = plan_request(
        "Which customer-feedback channels consistently indicate price sensitivity?", decision
    )

    assert planned.route is ConversationRoute.TOOL_CALL
    assert planned.tool_name is ChatToolName.DOCUMENTS
    assert planned.sources == [AnalyticsSource.CUSTOMER_FEEDBACK]
    assert planned.structured_plan is not None


def test_competitor_announcement_uses_market_documents_not_name_lookup() -> None:
    question = (
        "Which competitor announced a renewal pricing change, what change did it announce, "
        "and when was the announcement published?"
    )
    planned = plan_request(
        question,
        ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.ANALYTICS,
            sources=[AnalyticsSource.COMPETITORS],
        ),
    )

    assert planned.tool_name is ChatToolName.DOCUMENTS
    assert planned.sources == [AnalyticsSource.MARKET_INTELLIGENCE]
    assert planned.document_categories == ["competitor"]


def test_broad_plan_caps_sub_questions_at_contract_limit() -> None:
    planned = plan_request(
        "Investigate claims, conversion, competitors, pricing history, market intelligence, "
        "and customer feedback.",
        ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.MULTI_SOURCE,
            sources=list(AnalyticsSource),
        ),
    )

    assert planned.structured_plan is not None
    assert len(planned.structured_plan.sub_questions) == 5


@pytest.mark.parametrize(
    ("question", "expected_type", "expected_sources"),
    [
        (
            "Which sources contain conflicting, incomplete or outdated information?",
            AnalysisQuestionType.RELIABILITY,
            set(AnalyticsSource),
        ),
        (
            "Identify an unusual portfolio trend and determine the most plausible causes.",
            AnalysisQuestionType.ROOT_CAUSE,
            set(AnalyticsSource),
        ),
        (
            "What patterns in customer feedback and conversion data suggest changing "
            "customer expectations or behaviour?",
            AnalysisQuestionType.CUSTOMER_BEHAVIOR,
            {AnalyticsSource.CONVERSION, AnalyticsSource.CUSTOMER_FEEDBACK},
        ),
        (
            "Review earlier pricing actions and what should be learned from them.",
            AnalysisQuestionType.PREVIOUS_DECISIONS,
            {
                AnalyticsSource.PRICING_HISTORY,
                AnalyticsSource.CLAIMS,
                AnalyticsSource.CONVERSION,
            },
        ),
        (
            "Which findings should be handled automatically and which need human escalation?",
            AnalysisQuestionType.GOVERNANCE_ESCALATION,
            set(AnalyticsSource),
        ),
    ],
)
def test_analytical_question_types_build_question_specific_plans(
    question: str,
    expected_type: AnalysisQuestionType,
    expected_sources: set[AnalyticsSource],
) -> None:
    planned = plan_request(
        question,
        ConversationDecision(
            route=ConversationRoute.TOOL_CALL,
            tool_name=ChatToolName.ANALYTICS,
        ),
    )

    assert planned.structured_plan is not None
    assert planned.structured_plan.analysis_type is expected_type
    assert set(planned.sources) == expected_sources
    assert len(planned.structured_plan.sub_questions) >= 2


def test_governance_question_cannot_be_answered_directly_without_evidence() -> None:
    planned = plan_request(
        (
            "Which findings should the copilot handle automatically, and which should be "
            "escalated to a human specialist before any decision is made?"
        ),
        ConversationDecision(
            route=ConversationRoute.DIRECT_ANSWER,
            response="Use human review for uncertain cases.",
        ),
    )

    assert planned.route is ConversationRoute.TOOL_CALL
    assert planned.tool_name is ChatToolName.MULTI_SOURCE
    assert planned.intent is ConversationIntent.INVESTIGATION
    assert set(planned.sources) == set(AnalyticsSource)
    assert planned.structured_plan is not None
    assert (
        planned.structured_plan.analysis_type
        is AnalysisQuestionType.GOVERNANCE_ESCALATION
    )


@pytest.mark.parametrize(
    ("question", "expected_type"),
    [
        (
            "Without recommending any pricing action, identify the most plausible "
            "customer-behaviour explanations for lower retention.",
            AnalysisQuestionType.ROOT_CAUSE,
        ),
        (
            "What happens if no pricing action is taken over the next six months?",
            AnalysisQuestionType.COUNTERFACTUAL,
        ),
    ],
)
def test_negated_pricing_action_language_does_not_request_a_recommendation(
    question: str,
    expected_type: AnalysisQuestionType,
) -> None:
    planned = plan_request(
        question,
        ConversationDecision(
            route=ConversationRoute.DIRECT_ANSWER,
            response="A generic answer that should be replaced by evidence.",
        ),
    )

    assert planned.route is ConversationRoute.TOOL_CALL
    assert planned.tool_name is ChatToolName.MULTI_SOURCE
    assert planned.intent is ConversationIntent.INVESTIGATION
    assert planned.structured_plan is not None
    assert planned.structured_plan.analysis_type is expected_type


def test_repair_cost_question_uses_only_document_retrieval_with_chunk_evidence(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    retrieved = RetrievedDocument(
        document=DocumentRecord(
            document_id="mi-controlled-repair-2025-10",
            source_type=SourceType.REPAIR_COST_REPORT,
            title="Repair-cost inflation update",
            body="Parts, paint and labour costs rose materially.",
            source_date="2025-10-01",
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.NORTH_WEST,
            sentiment=DocumentSentiment.SUPPORTS_INCREASE,
        ),
        score=0.8,
        chunk_id="mi-controlled-repair-2025-10:chunk-001",
        source="Synthetic Motor Cost Index",
        retrieval_score=0.8,
    )
    with (
        patch("pricing_copilot.chat.service.retrieve_documents", return_value=[retrieved]),
        patch.object(
            service.tools,
            "_run_pricing_analysis",
            side_effect=AssertionError(
                "narrow document request must not run the portfolio workflow"
            ),
        ),
    ):
        response = service.submit("What do repair-cost reports say?")

    assert response.intent is ChatIntent.DATA_RETRIEVAL
    assert response.cited_evidence_ids == ["mi-controlled-repair-2025-10:chunk-001"]
    assert response.tables[0].title == "Market Intelligence"
    assert response.tables[0].columns[-1] == "relevant_text"
    assert response.tables[0].rows[0][0] == "mi-controlled-repair-2025-10"
    assert response.tables[0].rows[0][4] == "mi-controlled-repair-2025-10:chunk-001"


def test_no_matching_document_returns_insufficient_evidence_without_a_recommendation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    with (
        patch("pricing_copilot.chat.service.retrieve_documents", return_value=[]),
        patch.object(
            service.tools,
            "_run_pricing_analysis",
            side_effect=AssertionError(
                "narrow document request must not run the portfolio workflow"
            ),
        ),
    ):
        response = service.submit("What do repair-cost reports say?")

    assert "insufficient evidence" in response.message.lower()
    assert response.limitations
    assert not response.cited_evidence_ids
    assert response.context.scenario is ScenarioName.CONTROLLED_INCREASE


def test_attrition_question_uses_only_customer_feedback_and_composes_an_investigation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    documents = [
        RetrievedDocument(
            document=DocumentRecord(
                document_id=document_id,
                source_type=source_type,
                title=title,
                body=body,
                source_date="2025-12-01",
                scenario=ScenarioName.RETENTION_CONCERN,
                region=Region.NORTH_WEST,
                sentiment=DocumentSentiment.AGAINST_INCREASE,
            ),
            score=0.8,
            chunk_id=f"{document_id}:chunk-001",
            source="Synthetic source",
            retrieval_score=0.8,
        )
        for document_id, source_type, title, body in (
            (
                "cf-retention-cancellation-2025-11",
                SourceType.CUSTOMER_FEEDBACK,
                "Cancellation themes",
                "Price is the most frequent renewal cancellation theme.",
            ),
            (
                "cf-retention-affordability-2025-12",
                SourceType.CUSTOMER_FEEDBACK,
                "Affordability feedback",
                "Do not assume another increase will be accepted.",
            ),
            (
                "cf-retention-calls-2025-12",
                SourceType.CUSTOMER_FEEDBACK,
                "Call-centre themes",
                "Renewal callers frequently report comparison shopping.",
            ),
        )
    ]
    question = (
        "What evidence indicates that renewal pricing is contributing to customer attrition, "
        "and what investigation should follow?"
    )
    with (
        patch("pricing_copilot.chat.service.retrieve_documents", return_value=documents),
        patch.object(
            service.tools,
            "_run_pricing_analysis",
            side_effect=AssertionError(
                "retention investigation must not run the portfolio workflow"
            ),
        ),
    ):
        response = service.submit(question)

    assert response.intent is ChatIntent.DATA_RETRIEVAL
    assert {table.title for table in response.tables} == {"Customer Feedback"}
    assert "cf-retention-cancellation-2025-11:chunk-001" in response.message
    assert "cf-retention-affordability-2025-12:chunk-001" in response.message
    assert "cf-retention-calls-2025-12:chunk-001" in response.message
    assert "## Direct answer" in response.message
    assert "Renewal pricing appears to be contributing to attrition" in response.message
    assert "retention and price-elasticity investigation should follow" in response.message
    assert "## Supporting evidence" in response.message
    assert "## Investigation or limitation" in response.message
    assert "## Citations" in response.message
    assert response.context.scenario is ScenarioName.RETENTION_CONCERN
    assert any("Sub-questions:" in item for item in response.plan_details)
    assert any("customer feedback:" in item for item in response.plan_details)
    assert any("Evidence rule:" in item for item in response.plan_details)
    assert all(activity.label != "Portfolio analysis workflow" for activity in response.activities)


def test_price_sensitivity_question_composes_channels_and_common_pattern(tmp_path: Path) -> None:
    service = _service(tmp_path)
    documents = [
        RetrievedDocument(
            document=DocumentRecord(
                document_id=document_id,
                source_type=SourceType.CUSTOMER_FEEDBACK,
                title=title,
                body=body,
                source_date="2025-12-01",
                scenario=ScenarioName.RETENTION_CONCERN,
                region=Region.NORTH_WEST,
                sentiment=DocumentSentiment.AGAINST_INCREASE,
            ),
            score=0.8,
            chunk_id=f"{document_id}:chunk-001",
            source="Synthetic source",
            retrieval_score=0.8,
        )
        for document_id, title, body in (
            (
                "cf-cancellation",
                "Cancellation records",
                "Price is the most frequent renewal cancellation theme.",
            ),
            (
                "cf-affordability",
                "Affordability feedback",
                "Affordability concerns continue across renewal cycles.",
            ),
            (
                "cf-calls",
                "Call-centre themes",
                "Customers report comparison shopping after the previous increase.",
            ),
        )
    ]
    with patch("pricing_copilot.chat.service.retrieve_documents", return_value=documents):
        response = service.submit(
            "Which customer-feedback channels consistently indicate price sensitivity, and "
            "what common pattern appears across them?"
        )

    assert {table.title for table in response.tables} == {"Customer Feedback"}
    assert (
        "Cancellation records, affordability feedback, and call-centre conversations"
        in response.message
    )
    assert "common pattern is repeated price concern, comparison shopping" in response.message
    assert "conversion data tool" not in response.message


def test_controlled_increase_feedback_composes_scoped_negative_conclusion(tmp_path: Path) -> None:
    service = _service(tmp_path)
    documents = [
        RetrievedDocument(
            document=DocumentRecord(
                document_id="cf-controlled",
                source_type=SourceType.CUSTOMER_FEEDBACK,
                title="Controlled increase feedback",
                body=(
                    "Price-related comments are a small minority, with no recurring affordability "
                    "theme and no concentrated fairness concern. Claims handling, communication, "
                    "documentation and claims status dominate feedback."
                ),
                source_date="2025-12-01",
                scenario=ScenarioName.CONTROLLED_INCREASE,
                region=Region.NORTH_WEST,
                sentiment=DocumentSentiment.NEUTRAL,
            ),
            score=0.9,
            chunk_id="cf-controlled:chunk-001",
            source="Synthetic source",
            retrieval_score=0.9,
        )
    ]
    with patch("pricing_copilot.chat.service.retrieve_documents", return_value=documents):
        response = service.submit(
            "Does customer feedback in the controlled-increase scenario show a material "
            "affordability or fairness concern?"
        )

    assert "No material affordability or fairness concern is evidenced" in response.message
    assert "Price-related comments are a small minority" in response.message
    assert "claims handling, communication, documentation, or claims status" in response.message
