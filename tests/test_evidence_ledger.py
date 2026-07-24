from datetime import UTC, datetime

from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.data.repository import PortfolioDataRepository
from pricing_copilot.analytics.calculators import (
    calculate_claims_metrics,
    calculate_competitor_metrics,
    calculate_conversion_metrics,
    summarize_pricing_history,
)
from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.evidence.ledger import build_evidence_ledger


def _analytics() -> PortfolioAnalytics:
    repo = PortfolioDataRepository.from_scenario(ScenarioName.CONTROLLED_INCREASE)
    claims = calculate_claims_metrics(
        repo.fetch_claims(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    )
    conversion = calculate_conversion_metrics(
        repo.fetch_conversion(Product.PERSONAL_MOTOR, Region.NORTH_WEST), Segment.RENEWAL
    )
    competitors = calculate_competitor_metrics(repo.fetch_competitors(Region.NORTH_WEST))
    pricing_history = summarize_pricing_history(
        repo.fetch_pricing_history(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    )
    return PortfolioAnalytics(
        claims=claims, conversion=conversion, competitors=competitors, pricing_history=pricing_history
    )


def test_ledger_contains_one_entry_per_structured_metric_and_per_document() -> None:
    analytics = _analytics()
    documents = retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        region=Region.NORTH_WEST,
        query="claims conversion competitor broker feedback",
        top_k=6,
    )
    ledger = build_evidence_ledger(
        analytics=analytics, documents=documents, region=Region.NORTH_WEST, retrieved_at=datetime.now(UTC)
    )

    structured_entries = [e for e in ledger.entries if e.source_type == "structured_metric"]
    document_entries = [e for e in ledger.entries if e.source_type != "structured_metric"]

    assert len(document_entries) == len(documents)
    assert {e.evidence_id for e in document_entries} == {d.document.document_id for d in documents}
    assert any(e.metric_name == "loss_ratio" for e in structured_entries)
    assert any(e.metric_name == "quote_to_sale_conversion" for e in structured_entries)
    assert any(e.metric_name == "price_change_pct" for e in structured_entries)


def test_ledger_lookup_by_id_and_ids_set() -> None:
    analytics = _analytics()
    ledger = build_evidence_ledger(
        analytics=analytics, documents=[], region=Region.NORTH_WEST, retrieved_at=datetime.now(UTC)
    )
    an_id = next(iter(ledger.ids()))
    assert ledger.get(an_id) is not None
    assert ledger.get("does-not-exist") is None
