from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from pricing_copilot.config import Settings
from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.documents.corpus import DocumentRecord, documents_for_scenario
from pricing_copilot.intelligence.contracts import RetrievalFilters, source_type_for_document_type
from pricing_copilot.intelligence.retrieval import HybridRetriever, MarketIntelligenceUnavailable

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class RetrievedDocument(BaseModel):
    document: DocumentRecord
    score: float
    chunk_id: str | None = None
    source: str | None = None
    retrieval_score: float | None = None
    vector_score: float | None = None
    keyword_score: float | None = None
    file_path: str | None = None

    @property
    def evidence_id(self) -> str:
        return self.chunk_id or self.document.document_id


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def retrieve_documents(
    *,
    scenario: ScenarioName,
    region: Region,
    query: str,
    top_k: int = 6,
    settings: Settings | None = None,
    product: Product | None = None,
    segment: Segment | None = None,
    categories: list[str] | None = None,
    publication_date_from: date | None = None,
    publication_date_to: date | None = None,
) -> list[RetrievedDocument]:
    """Retrieve persistent hybrid evidence when indexed, else preserve legacy corpus access.

    The fallback keeps existing deterministic scenarios runnable before the first
    Azure-backed ingestion.  A configured and ready index always takes precedence.
    """
    if settings is not None:
        try:
            retriever = HybridRetriever.from_settings(settings)
            evidence, _latency_ms = retriever.retrieve(
                query,
                RetrievalFilters(
                    scenario=scenario,
                    product=product,
                    region=region,
                    segment=segment,
                    categories=categories or [],
                    publication_date_from=publication_date_from,
                    publication_date_to=publication_date_to,
                ),
                top_k=top_k,
            )
        except (MarketIntelligenceUnavailable, RuntimeError):
            evidence = []
        if evidence:
            return [
                RetrievedDocument(
                    document=DocumentRecord(
                        document_id=item.document_id,
                        source_type=source_type_for_document_type(item.document_type),
                        title=item.title,
                        body=item.relevant_text,
                        source_date=item.publication_date,
                        scenario=scenario,
                        region=region,
                        sentiment=item.sentiment,
                    ),
                    score=item.retrieval_score,
                    chunk_id=item.chunk_id,
                    source=item.source,
                    retrieval_score=item.retrieval_score,
                    vector_score=item.vector_score,
                    keyword_score=item.keyword_score,
                    file_path=item.file_path,
                )
                for item in evidence
            ]
    if categories or publication_date_from or publication_date_to:
        return []
    candidates = documents_for_scenario(scenario, region)
    if not candidates:
        return []

    corpus_tokens = [_tokenize(f"{d.title} {d.body}") for d in candidates]
    bm25 = BM25Okapi(corpus_tokens)
    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [RetrievedDocument(document=doc, score=float(score)) for doc, score in ranked[:top_k]]
