from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
