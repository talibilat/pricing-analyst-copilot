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
from pricing_copilot.recommendation.synthesizer import FakeRecommendationSynthesizer


def test_fake_synthesizer_cites_only_ids_present_in_the_ledger() -> None:
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
    analytics = PortfolioAnalytics(
        claims=claims, conversion=conversion, competitors=competitors, pricing_history=pricing_history
    )
    documents = retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE, region=Region.NORTH_WEST, query="claims severity", top_k=4
    )
    ledger = build_evidence_ledger(
        analytics=analytics, documents=documents, region=Region.NORTH_WEST, retrieved_at=datetime.now(UTC)
    )

    synthesizer = FakeRecommendationSynthesizer()
    draft = synthesizer.synthesize(
        analytics=analytics, ledger=ledger, documents=documents, max_movement_pct=5.0
    )

    assert draft.cited_evidence_ids
    assert set(draft.cited_evidence_ids).issubset(ledger.ids())
    assert draft.price_range is not None
    assert draft.price_range.lower_pct >= 0
    assert draft.price_range.upper_pct <= 5.0
