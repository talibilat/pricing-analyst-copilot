from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.contracts import Region
from pricing_copilot.documents.retrieval import RetrievedDocument


class EvidenceLedgerEntry(BaseModel):
    evidence_id: str
    source_type: str
    source_reference: str
    source_date: date | None = None
    retrieval_timestamp: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    metric_name: str | None = None
    value: float | None = None
    baseline_value: float | None = None
    interpretation: str


class EvidenceLedger(BaseModel):
    entries: list[EvidenceLedgerEntry] = Field(default_factory=list)

    def get(self, evidence_id: str) -> EvidenceLedgerEntry | None:
        for entry in self.entries:
            if entry.evidence_id == evidence_id:
                return entry
        return None

    def ids(self) -> set[str]:
        return {entry.evidence_id for entry in self.entries}


class ConfidenceBreakdown(BaseModel):
    evidence_coverage: float
    source_freshness: float
    specialist_agreement: float
    data_quality: float
    conflict_penalty: float
    overall: float


class FairValueStatus(StrEnum):
    NO_CONCERN = "no_concern"
    REVIEW_RECOMMENDED = "review_recommended"
    CONCERN_IDENTIFIED = "concern_identified"


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
                interpretation=f"Previous {action.price_change_pct:+.1f}% action: {action.rationale}",
            )
        )

    for retrieved in documents:
        document = retrieved.document
        entries.append(
            EvidenceLedgerEntry(
                evidence_id=document.document_id,
                source_type=document.source_type.value,
                source_reference=document.title,
                source_date=document.source_date,
                retrieval_timestamp=retrieved_at,
                interpretation=document.title,
            )
        )

    return EvidenceLedger(entries=entries)
