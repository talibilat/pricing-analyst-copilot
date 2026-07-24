from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentSentiment, SourceType, documents_for_scenario


def test_controlled_increase_corpus_covers_all_required_source_types() -> None:
    documents = documents_for_scenario(ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST)
    source_types = {d.source_type for d in documents}
    assert source_types == {
        SourceType.MARKET_REPORT,
        SourceType.REPAIR_COST_REPORT,
        SourceType.CUSTOMER_FEEDBACK,
        SourceType.BROKER_NOTE,
    }


def test_every_document_is_marked_synthetic_with_stable_id_and_date() -> None:
    documents = documents_for_scenario(ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST)
    ids = [d.document_id for d in documents]
    assert len(ids) == len(set(ids))
    assert all(d.is_synthetic for d in documents)
    assert all(d.source_date is not None for d in documents)


def test_corpus_includes_an_adversarial_prompt_injection_fixture() -> None:
    documents = documents_for_scenario(ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST)
    adversarial = [d for d in documents if "SYSTEM OVERRIDE" in d.body]
    assert len(adversarial) == 1
    assert adversarial[0].source_type == SourceType.MARKET_REPORT


def test_retention_concern_corpus_has_documents_all_against_increase_or_neutral() -> None:
    documents = documents_for_scenario(ScenarioName.RETENTION_CONCERN, Region.NORTH_WEST)
    assert documents
    assert all(
        d.sentiment in (DocumentSentiment.AGAINST_INCREASE, DocumentSentiment.NEUTRAL)
        for d in documents
    )
    feedback_docs = [d for d in documents if d.source_type == SourceType.CUSTOMER_FEEDBACK]
    assert len(feedback_docs) >= 2


def test_conflicting_evidence_corpus_has_two_conflicting_market_reports() -> None:
    documents = documents_for_scenario(ScenarioName.CONFLICTING_EVIDENCE, Region.NORTH_WEST)
    market_reports = [d for d in documents if d.source_type == SourceType.MARKET_REPORT]
    sentiments = {d.sentiment for d in market_reports}
    assert DocumentSentiment.SUPPORTS_INCREASE in sentiments
    assert DocumentSentiment.AGAINST_INCREASE in sentiments


def test_conflicting_evidence_corpus_has_a_stale_document() -> None:
    from datetime import date

    documents = documents_for_scenario(ScenarioName.CONFLICTING_EVIDENCE, Region.NORTH_WEST)
    assert any((date(2025, 12, 15) - d.source_date).days > 120 for d in documents)


def test_documents_are_filtered_by_region() -> None:
    documents = documents_for_scenario(ScenarioName.CONTROLLED_INCREASE, Region.SOUTH_EAST)
    assert documents == []
    assert documents_for_scenario(ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST) != []


def test_sentiment_tags_are_present_and_typed() -> None:
    documents = documents_for_scenario(ScenarioName.CONTROLLED_INCREASE, Region.NORTH_WEST)
    assert all(isinstance(d.sentiment, DocumentSentiment) for d in documents)
