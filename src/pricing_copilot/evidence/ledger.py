from __future__ import annotations

from datetime import datetime

from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.contracts import Region
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.models import EvidenceLedger, EvidenceLedgerEntry


def build_evidence_ledger(
    *,
    analytics: PortfolioAnalytics,
    documents: list[RetrievedDocument],
    region: Region,
    retrieved_at: datetime,
) -> EvidenceLedger:
    entries: list[EvidenceLedgerEntry] = [
        EvidenceLedgerEntry(
            evidence_id=f"claims-{region.value}-{analytics.claims.period_end.isoformat()}",
            source_type="structured_metric",
            source_reference="Deterministic claims analytics",
            period_start=analytics.claims.period_start,
            period_end=analytics.claims.period_end,
            metric_name="loss_ratio",
            value=analytics.claims.loss_ratio.current,
            baseline_value=analytics.claims.loss_ratio.baseline,
            interpretation=(
                f"Loss ratio moved from {analytics.claims.loss_ratio.baseline:.1%} to "
                f"{analytics.claims.loss_ratio.current:.1%}."
            ),
        ),
        EvidenceLedgerEntry(
            evidence_id=f"conversion-{region.value}-{analytics.conversion.period_end.isoformat()}",
            source_type="structured_metric",
            source_reference="Deterministic conversion analytics",
            period_start=analytics.conversion.period_start,
            period_end=analytics.conversion.period_end,
            metric_name="quote_to_sale_conversion",
            value=analytics.conversion.quote_to_sale_conversion.current,
            baseline_value=analytics.conversion.quote_to_sale_conversion.baseline,
            interpretation=(
                "Quote-to-sale conversion moved from "
                f"{analytics.conversion.quote_to_sale_conversion.baseline:.1%} to "
                f"{analytics.conversion.quote_to_sale_conversion.current:.1%}."
            ),
        ),
        EvidenceLedgerEntry(
            evidence_id=f"retention-{region.value}-{analytics.conversion.period_end.isoformat()}",
            source_type="structured_metric",
            source_reference="Deterministic conversion analytics",
            period_start=analytics.conversion.period_start,
            period_end=analytics.conversion.period_end,
            metric_name="renewal_retention",
            value=analytics.conversion.renewal_retention.current,
            baseline_value=analytics.conversion.renewal_retention.baseline,
            interpretation=(
                "Renewal retention moved from "
                f"{analytics.conversion.renewal_retention.baseline:.1%} to "
                f"{analytics.conversion.renewal_retention.current:.1%}."
            ),
        ),
    ]

    if analytics.competitors.competitors:
        average_movement = sum(
            m.price_index.movement_pct or 0.0 for m in analytics.competitors.competitors
        ) / len(analytics.competitors.competitors)
        entries.append(
            EvidenceLedgerEntry(
                evidence_id=f"competitors-{region.value}-{analytics.competitors.period_end.isoformat()}",
                source_type="structured_metric",
                source_reference="Deterministic competitor analytics",
                period_start=analytics.competitors.period_start,
                period_end=analytics.competitors.period_end,
                metric_name="competitor_index_average_movement_pct",
                value=round(average_movement, 1),
                interpretation=(
                    f"{len(analytics.competitors.competitors)} fictional competitors tracked; "
                    f"average price-index movement {average_movement:+.1f}%."
                ),
            )
        )

    for action in analytics.pricing_history:
        entries.append(
            EvidenceLedgerEntry(
                evidence_id=f"pricing-history-{action.period.isoformat()}",
                source_type="structured_metric",
                source_reference="Previous pricing action record",
                period_start=action.period,
                period_end=action.period,
                metric_name="price_change_pct",
                value=action.price_change_pct,
                interpretation=(
                    f"Previous {action.price_change_pct:+.1f}% action: {action.rationale}"
                ),
            )
        )

    for retrieved in documents:
        document = retrieved.document
        entries.append(
            EvidenceLedgerEntry(
                evidence_id=retrieved.evidence_id,
                source_type=document.source_type.value,
                source_reference=document.title,
                source_date=document.source_date,
                retrieval_timestamp=retrieved_at,
                interpretation=document.body,
                document_id=document.document_id,
                chunk_id=retrieved.chunk_id,
                retrieval_score=retrieved.retrieval_score or retrieved.score,
            )
        )

    return EvidenceLedger(entries=entries)
