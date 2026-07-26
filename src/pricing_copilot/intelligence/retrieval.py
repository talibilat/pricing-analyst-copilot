from __future__ import annotations

from time import perf_counter

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from pricing_copilot.config import Settings
from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.intelligence.contracts import RetrievalFilters, RetrievedEvidence
from pricing_copilot.intelligence.ingestion import AzureOpenAIEmbeddingClient, EmbeddingClient
from pricing_copilot.intelligence.store import IntelligenceCatalogue


class MarketIntelligenceUnavailable(RuntimeError):
    """The persistent index is not ready to serve a workflow retrieval."""


class HybridRetriever:
    """Metadata-first hybrid retrieval with reciprocal-rank fusion.

    Metadata and date filters are evaluated in the DuckDB catalogue before both
    semantic and keyword ranking, eliminating cross-scenario document leakage.
    """

    def __init__(self, settings: Settings, embedder: EmbeddingClient) -> None:
        self.settings = settings
        self.catalogue = IntelligenceCatalogue(settings.market_intelligence_database_path)
        self.embedder = embedder

    @classmethod
    def from_settings(cls, settings: Settings) -> HybridRetriever:
        from pricing_copilot.config import AzureOpenAISettings

        return cls(settings, AzureOpenAIEmbeddingClient(AzureOpenAISettings()))

    def is_ready(self) -> bool:
        if self.catalogue.active_ingestion_version() is None:
            return False
        if not self.settings.qdrant_path.exists():
            return False
        client = QdrantClient(path=str(self.settings.qdrant_path))
        try:
            return client.collection_exists(self.settings.qdrant_collection)
        finally:
            client.close()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        import re

        return re.findall(r"[a-z0-9]+", text.lower())

    @staticmethod
    def _rrf(rank: int, constant: int = 60) -> float:
        return 1 / (constant + rank)

    def retrieve(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int = 6,
        keyword_search: bool = True,
    ) -> tuple[list[RetrievedEvidence], float]:
        started = perf_counter()
        if not self.is_ready():
            raise MarketIntelligenceUnavailable(
                "Market-intelligence index is unavailable. Run --ingest-market-intelligence first."
            )
        rows = self.catalogue.filtered_chunk_rows(filters)
        if not rows:
            return [], (perf_counter() - started) * 1000
        query_vector = self.embedder.embed([query])[0]
        payload_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="scenario", match=models.MatchValue(value=filters.scenario.value)
                ),
                *(
                    [
                        models.FieldCondition(
                            key="product", match=models.MatchValue(value=filters.product.value)
                        )
                    ]
                    if filters.product
                    else []
                ),
                *(
                    [
                        models.FieldCondition(
                            key="region", match=models.MatchValue(value=filters.region.value)
                        )
                    ]
                    if filters.region
                    else []
                ),
                *(
                    [
                        models.FieldCondition(
                            key="segment", match=models.MatchValue(value=filters.segment.value)
                        )
                    ]
                    if filters.segment
                    else []
                ),
                *(
                    [
                        models.FieldCondition(
                            key="category", match=models.MatchAny(any=filters.categories)
                        )
                    ]
                    if filters.categories
                    else []
                ),
            ]
        )
        client = QdrantClient(path=str(self.settings.qdrant_path))
        try:
            response = client.query_points(
                collection_name=self.settings.qdrant_collection,
                query=query_vector,
                query_filter=payload_filter,
                limit=max(top_k * 4, 20),
                with_payload=True,
            )
            semantic = list(response.points)
        finally:
            client.close()
        permitted_ids = {str(row["chunk_id"]) for row in rows}
        semantic_scores = {
            str(point.payload["chunk_id"]): float(point.score)
            for point in semantic
            if point.payload is not None and str(point.payload["chunk_id"]) in permitted_ids
        }
        keyword_scores: dict[str, float] = {}
        if keyword_search:
            corpus = [str(row["chunk_id"]) for row in rows]
            texts = [self._text_from_row(row) for row in rows]
            bm25 = BM25Okapi([self._tokens(text) for text in texts])
            keyword_scores = {
                chunk_id: float(score)
                for chunk_id, score in zip(
                    corpus, bm25.get_scores(self._tokens(query)), strict=True
                )
            }

        fused: dict[str, float] = {}
        for rank, chunk_id in enumerate(
            sorted(semantic_scores, key=lambda item: semantic_scores[item], reverse=True), start=1
        ):
            fused[chunk_id] = fused.get(chunk_id, 0) + self._rrf(rank)
        if keyword_search:
            for rank, chunk_id in enumerate(
                sorted(keyword_scores, key=lambda item: keyword_scores[item], reverse=True), start=1
            ):
                fused[chunk_id] = fused.get(chunk_id, 0) + self._rrf(rank)

        row_by_chunk_id = {str(row["chunk_id"]): row for row in rows}
        evidence = [
            RetrievedEvidence(
                document_id=str(row_by_chunk_id[chunk_id]["document_id"]),
                chunk_id=chunk_id,
                title=str(row_by_chunk_id[chunk_id]["title"]),
                source=str(row_by_chunk_id[chunk_id]["source"]),
                publication_date=row_by_chunk_id[chunk_id]["publication_date"],  # type: ignore[arg-type]
                document_type=str(row_by_chunk_id[chunk_id]["document_type"]),
                category=str(row_by_chunk_id[chunk_id]["category"]),
                sentiment=str(row_by_chunk_id[chunk_id]["sentiment"]),  # type: ignore[arg-type]
                product=Product(str(row_by_chunk_id[chunk_id]["product"])),
                region=Region(str(row_by_chunk_id[chunk_id]["region"])),
                segment=Segment(str(row_by_chunk_id[chunk_id]["segment"])),
                scenario=ScenarioName(str(row_by_chunk_id[chunk_id]["scenario"])),
                file_path=str(row_by_chunk_id[chunk_id]["file_path"]),
                relevant_text=self._text_from_row(row_by_chunk_id[chunk_id]),
                retrieval_score=round(score, 8),
                vector_score=semantic_scores.get(chunk_id),
                keyword_score=keyword_scores.get(chunk_id),
                ingestion_version=str(row_by_chunk_id[chunk_id]["ingestion_version"]),
            )
            for chunk_id, score in sorted(fused.items(), key=lambda item: item[1], reverse=True)[
                :top_k
            ]
        ]
        return evidence, (perf_counter() - started) * 1000

    @staticmethod
    def _text_from_row(row: dict[str, object]) -> str:
        import json
        from pathlib import Path

        from pricing_copilot.intelligence.chunking import chunk_document

        source = Path(str(row["file_path"]))
        payload = json.loads(source.read_text())
        document_id = str(row["document_id"])
        document = next(item for item in payload if item["document_id"] == document_id)
        chunk_id = str(row["chunk_id"])
        return next(
            chunk.text
            for chunk in chunk_document(document_id, str(document["content"]))
            if chunk.chunk_id == chunk_id
        )
