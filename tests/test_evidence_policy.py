from datetime import date

from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.policy import detect_material_evidence_issues


def _document(
    document_id: str,
    source_type: SourceType,
    sentiment: DocumentSentiment,
    source_date: date,
) -> RetrievedDocument:
    return RetrievedDocument(
        document=DocumentRecord(
            document_id=document_id,
            source_type=source_type,
            title="t",
            body="b",
            source_date=source_date,
            scenario=ScenarioName.CONFLICTING_EVIDENCE,
            region=Region.NORTH_WEST,
            sentiment=sentiment,
        ),
        score=1.0,
    )


def test_no_issues_for_fresh_consistent_documents() -> None:
    documents = [
        _document(
            "d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 12, 1)
        ),
        _document("d2", SourceType.BROKER_NOTE, DocumentSentiment.NEUTRAL, date(2025, 11, 15)),
    ]
    assert (
        detect_material_evidence_issues(
            documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
        )
        == []
    )


def test_stale_document_is_flagged() -> None:
    documents = [
        _document(
            "d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 1, 1)
        ),
    ]
    issues = detect_material_evidence_issues(
        documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    )
    assert len(issues) == 1
    assert "d1" in issues[0]
    assert "market_intelligence" in issues[0]


def test_conflicting_same_type_documents_are_flagged() -> None:
    documents = [
        _document(
            "d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 12, 1)
        ),
        _document(
            "d2", SourceType.MARKET_REPORT, DocumentSentiment.AGAINST_INCREASE, date(2025, 12, 1)
        ),
    ]
    issues = detect_material_evidence_issues(
        documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    )
    assert len(issues) == 1
    assert "conflicting" in issues[0]


def test_conflicting_different_type_documents_are_not_flagged() -> None:
    documents = [
        _document(
            "d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 12, 1)
        ),
        _document(
            "d2",
            SourceType.CUSTOMER_FEEDBACK,
            DocumentSentiment.AGAINST_INCREASE,
            date(2025, 12, 1),
        ),
    ]
    assert (
        detect_material_evidence_issues(
            documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
        )
        == []
    )


def test_no_documents_has_no_issues() -> None:
    assert (
        detect_material_evidence_issues(
            [], analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
        )
        == []
    )
