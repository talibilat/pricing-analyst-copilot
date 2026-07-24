from __future__ import annotations

from datetime import date

from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.documents.corpus import DocumentSentiment
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.ledger import ConfidenceBreakdown, EvidenceLedger

FRESHNESS_DECAY_DAYS = 180.0
CONVERSION_TOLERANCE_PCT = -10.0


def calculate_confidence(
    *,
    ledger: EvidenceLedger,
    documents: list[RetrievedDocument],
    analytics: PortfolioAnalytics,
    action: RecommendationAction,
    analysis_period_end: date,
) -> ConfidenceBreakdown:
    required_domains = {"claims", "conversion", "market_intelligence", "pricing_history"}
    covered: set[str] = set()
    if any(e.metric_name == "loss_ratio" for e in ledger.entries):
        covered.add("claims")
    if any(e.metric_name == "quote_to_sale_conversion" for e in ledger.entries):
        covered.add("conversion")
    if any((e.metric_name or "").startswith("competitor") for e in ledger.entries) or documents:
        covered.add("market_intelligence")
    if any(e.metric_name == "price_change_pct" for e in ledger.entries):
        covered.add("pricing_history")
    evidence_coverage = len(covered) / len(required_domains)

    if documents:
        freshness_scores = [
            max(0.0, 1.0 - (analysis_period_end - r.document.source_date).days / FRESHNESS_DECAY_DAYS)
            for r in documents
        ]
        source_freshness = sum(freshness_scores) / len(freshness_scores)
    else:
        source_freshness = 1.0

    loss_ratio_movement = analytics.claims.loss_ratio.movement_pct or 0.0
    competitor_movements = [
        m.price_index.movement_pct or 0.0 for m in analytics.competitors.competitors
    ]
    average_competitor_movement = (
        sum(competitor_movements) / len(competitor_movements) if competitor_movements else 0.0
    )
    conversion_movement = analytics.conversion.quote_to_sale_conversion.movement_pct or 0.0

    if action is RecommendationAction.INCREASE:
        checks = [
            loss_ratio_movement > 0,
            average_competitor_movement > 0,
            conversion_movement > CONVERSION_TOLERANCE_PCT,
        ]
    else:
        checks = [True]
    specialist_agreement = sum(1 for c in checks if c) / len(checks)

    data_quality = 1.0

    if documents and action is RecommendationAction.INCREASE:
        against = sum(
            1 for r in documents if r.document.sentiment == DocumentSentiment.AGAINST_INCREASE
        )
        conflict_penalty = against / len(documents)
    else:
        conflict_penalty = 0.0

    overall = (
        evidence_coverage + source_freshness + specialist_agreement + data_quality + (1 - conflict_penalty)
    ) / 5

    return ConfidenceBreakdown(
        evidence_coverage=round(evidence_coverage, 4),
        source_freshness=round(source_freshness, 4),
        specialist_agreement=round(specialist_agreement, 4),
        data_quality=round(data_quality, 4),
        conflict_penalty=round(conflict_penalty, 4),
        overall=round(overall, 4),
    )
