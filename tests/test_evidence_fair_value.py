from datetime import date

from pricing_copilot.contracts import RecommendationAction, Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.fair_value import calculate_fair_value_status
from pricing_copilot.evidence.models import FairValueStatus


def _document(sentiment: DocumentSentiment) -> RetrievedDocument:
    return RetrievedDocument(
        document=DocumentRecord(
            document_id=f"doc-{sentiment.value}",
            source_type=SourceType.CUSTOMER_FEEDBACK,
            title="t",
            body="b",
            source_date=date(2025, 11, 1),
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.NORTH_WEST,
            sentiment=sentiment,
        ),
        score=1.0,
    )


def test_hold_action_has_no_fair_value_concern() -> None:
    status, follow_up = calculate_fair_value_status(
        action=RecommendationAction.HOLD, conversion_movement_pct=0.0, documents=[]
    )
    assert status is FairValueStatus.NO_CONCERN
    assert follow_up == []


def test_increase_with_resilient_conversion_recommends_review() -> None:
    status, follow_up = calculate_fair_value_status(
        action=RecommendationAction.INCREASE,
        conversion_movement_pct=-1.0,
        documents=[_document(DocumentSentiment.NEUTRAL)],
    )
    assert status is FairValueStatus.REVIEW_RECOMMENDED
    assert follow_up


def test_increase_with_multiple_against_documents_identifies_concern() -> None:
    status, follow_up = calculate_fair_value_status(
        action=RecommendationAction.INCREASE,
        conversion_movement_pct=-2.0,
        documents=[
            _document(DocumentSentiment.AGAINST_INCREASE),
            _document(DocumentSentiment.AGAINST_INCREASE),
        ],
    )
    assert status is FairValueStatus.CONCERN_IDENTIFIED
    assert follow_up


def test_increase_with_material_retention_drop_identifies_concern() -> None:
    status, _ = calculate_fair_value_status(
        action=RecommendationAction.INCREASE, conversion_movement_pct=-15.0, documents=[]
    )
    assert status is FairValueStatus.CONCERN_IDENTIFIED
