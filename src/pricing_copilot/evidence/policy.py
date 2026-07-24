from __future__ import annotations

from datetime import date

from pricing_copilot.documents.corpus import DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument

_CONFLICTING_PAIR = {DocumentSentiment.SUPPORTS_INCREASE, DocumentSentiment.AGAINST_INCREASE}


def detect_material_evidence_issues(
    documents: list[RetrievedDocument],
    *,
    analysis_period_end: date,
    max_evidence_age_days: int,
) -> list[str]:
    issues: list[str] = []

    stale = [
        retrieved
        for retrieved in documents
        if (analysis_period_end - retrieved.document.source_date).days > max_evidence_age_days
    ]
    if stale:
        stale_ids = ", ".join(retrieved.document.document_id for retrieved in stale)
        issues.append(
            f"market_intelligence: {len(stale)} retrieved document(s) exceed the "
            f"{max_evidence_age_days}-day evidence freshness policy ({stale_ids})."
        )

    sentiments_by_type: dict[SourceType, set[DocumentSentiment]] = {}
    for retrieved in documents:
        sentiments_by_type.setdefault(retrieved.document.source_type, set()).add(
            retrieved.document.sentiment
        )
    conflicting_types = [
        source_type.value
        for source_type, sentiments in sentiments_by_type.items()
        if _CONFLICTING_PAIR <= sentiments
    ]
    if conflicting_types:
        issues.append(
            "market_intelligence: materially conflicting "
            f"{', '.join(conflicting_types)} documents disagree on market direction and "
            "cannot be silently averaged away."
        )

    return issues
