from datetime import UTC, date, datetime

from pricing_copilot.analytics.contracts import (
    ClaimsMetrics,
    CompetitorMetrics,
    CompetitorMovement,
    ConversionMetrics,
    MonthlyValue,
    PortfolioAnalytics,
    PricingHistoryComparison,
    WindowMetric,
)
from pricing_copilot.contracts import RecommendationAction, Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.confidence import calculate_confidence
from pricing_copilot.evidence.ledger import build_evidence_ledger


def _window(baseline: float, current: float) -> WindowMetric:
    monthly = [MonthlyValue(period=date(2024, 1, 1), value=baseline)] * 12 + [
        MonthlyValue(period=date(2025, 1, 1), value=current)
    ] * 12
    movement = None if baseline == 0 else (current - baseline) / baseline * 100
    return WindowMetric(baseline=baseline, current=current, movement_pct=movement, monthly=monthly)


def _analytics(
    competitor_movement_pct: float = 2.5, conversion_movement_pct_input: float = 0.0
) -> PortfolioAnalytics:
    claims = ClaimsMetrics(
        period_start=date(2024, 1, 1),
        period_end=date(2025, 12, 1),
        claim_frequency=_window(0.08, 0.08),
        average_severity_gbp=_window(1600.0, 1860.0),
        incurred_loss_gbp=_window(500_000.0, 580_000.0),
        loss_ratio=_window(0.71, 0.82),
    )
    conversion_current = 0.22 * (1 + conversion_movement_pct_input / 100)
    conversion = ConversionMetrics(
        period_start=date(2024, 1, 1),
        period_end=date(2025, 12, 1),
        quote_to_sale_conversion=_window(0.22, conversion_current),
        renewal_retention=_window(0.88, 0.88),
        average_quoted_premium_gbp=_window(600.0, 610.0),
        segment_comparison={},
    )
    index_current = 100.0 * (1 + competitor_movement_pct / 100)
    competitors = CompetitorMetrics(
        period_start=date(2024, 1, 1),
        period_end=date(2025, 12, 1),
        competitors=[
            CompetitorMovement(
                competitor_name="Test Insurer",
                price_index=_window(100.0, index_current),
                rank=_window(1.0, 1.0),
            )
        ],
    )
    pricing_history = [
        PricingHistoryComparison(
            period=date(2024, 6, 1),
            price_change_pct=2.0,
            rationale="Test previous action.",
            conversion_impact_pct=-0.5,
            loss_ratio_impact_pct=-1.0,
        )
    ]
    return PortfolioAnalytics(
        claims=claims,
        conversion=conversion,
        competitors=competitors,
        pricing_history=pricing_history,
    )


def _document(sentiment: DocumentSentiment, source_date: date) -> RetrievedDocument:
    return RetrievedDocument(
        document=DocumentRecord(
            document_id=f"doc-{sentiment.value}-{source_date.isoformat()}",
            source_type=SourceType.MARKET_REPORT,
            title="Test document",
            body="Test body",
            source_date=source_date,
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.NORTH_WEST,
            sentiment=sentiment,
        ),
        score=1.0,
    )


def test_confidence_is_high_when_signals_agree_and_evidence_is_fresh() -> None:
    analytics = _analytics()
    documents = [_document(DocumentSentiment.SUPPORTS_INCREASE, date(2025, 11, 1))]
    ledger = build_evidence_ledger(
        analytics=analytics,
        documents=documents,
        region=Region.NORTH_WEST,
        retrieved_at=datetime.now(UTC),
    )
    breakdown = calculate_confidence(
        ledger=ledger,
        documents=documents,
        analytics=analytics,
        action=RecommendationAction.INCREASE,
        analysis_period_end=date(2025, 12, 1),
    )
    assert breakdown.evidence_coverage == 1.0
    assert breakdown.specialist_agreement == 1.0
    assert breakdown.conflict_penalty == 0.0
    assert 0.0 <= breakdown.overall <= 1.0
    assert breakdown.overall > 0.8


def test_confidence_drops_with_conflicting_documents() -> None:
    analytics = _analytics()
    documents = [
        _document(DocumentSentiment.AGAINST_INCREASE, date(2025, 11, 1)),
        _document(DocumentSentiment.SUPPORTS_INCREASE, date(2025, 11, 2)),
    ]
    ledger = build_evidence_ledger(
        analytics=analytics,
        documents=documents,
        region=Region.NORTH_WEST,
        retrieved_at=datetime.now(UTC),
    )
    breakdown = calculate_confidence(
        ledger=ledger,
        documents=documents,
        analytics=analytics,
        action=RecommendationAction.INCREASE,
        analysis_period_end=date(2025, 12, 1),
    )
    assert breakdown.conflict_penalty == 0.5


def test_confidence_with_no_documents_uses_full_freshness() -> None:
    analytics = _analytics()
    ledger = build_evidence_ledger(
        analytics=analytics, documents=[], region=Region.NORTH_WEST, retrieved_at=datetime.now(UTC)
    )
    breakdown = calculate_confidence(
        ledger=ledger,
        documents=[],
        analytics=analytics,
        action=RecommendationAction.HOLD,
        analysis_period_end=date(2025, 12, 1),
    )
    assert breakdown.source_freshness == 1.0
    assert breakdown.specialist_agreement == 1.0
