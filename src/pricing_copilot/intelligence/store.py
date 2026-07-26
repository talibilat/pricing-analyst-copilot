from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pricing_copilot.intelligence.contracts import (
    IngestionRun,
    IntelligenceChunk,
    RawIntelligenceDocument,
    RetrievalFilters,
)


class IntelligenceCatalogue:
    """DuckDB catalogue for document metadata and chunk manifests only.

    Raw text remains in source JSON files and Qdrant.  This database is separate
    from the protected synthetic portfolio analytics artifact.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.path))
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS document_catalogue (
                document_id VARCHAR PRIMARY KEY,
                title VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                publication_date DATE NOT NULL,
                document_type VARCHAR NOT NULL,
                product VARCHAR NOT NULL,
                region VARCHAR NOT NULL,
                segment VARCHAR NOT NULL,
                category VARCHAR NOT NULL,
                scenario VARCHAR NOT NULL,
                sentiment VARCHAR NOT NULL,
                file_path VARCHAR NOT NULL,
                content_hash VARCHAR NOT NULL,
                dataset_version VARCHAR NOT NULL,
                ingestion_version VARCHAR NOT NULL,
                ingested_at TIMESTAMP NOT NULL)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id VARCHAR PRIMARY KEY,
                document_id VARCHAR NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_hash VARCHAR NOT NULL,
                character_count INTEGER NOT NULL,
                dataset_version VARCHAR NOT NULL,
                ingestion_version VARCHAR NOT NULL)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS ingestion_runs (
                ingestion_version VARCHAR PRIMARY KEY,
                dataset_version VARCHAR NOT NULL,
                embedding_model VARCHAR NOT NULL,
                started_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                document_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                status VARCHAR NOT NULL)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS retrieval_evaluation_runs (
                run_id VARCHAR PRIMARY KEY,
                evaluated_at TIMESTAMP NOT NULL,
                dataset_version VARCHAR NOT NULL,
                recall_at_k DOUBLE NOT NULL,
                precision_at_k DOUBLE NOT NULL,
                metadata_filter_accuracy DOUBLE NOT NULL,
                citation_correctness DOUBLE NOT NULL,
                unsupported_claim_rate DOUBLE NOT NULL,
                retrieval_latency_ms_p95 DOUBLE NOT NULL)"""
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS recommendation_outcomes ("
                "outcome_id VARCHAR PRIMARY KEY, recommendation_action VARCHAR NOT NULL, "
                "confidence_score DOUBLE, human_review_result VARCHAR, business_outcome VARCHAR, "
                "recorded_at TIMESTAMP NOT NULL, payload JSON NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS intelligence_drift_metrics ("
                "ingestion_version VARCHAR PRIMARY KEY, recorded_at TIMESTAMP NOT NULL, "
                "embedding_model VARCHAR NOT NULL, document_count INTEGER NOT NULL, "
                "chunk_count INTEGER NOT NULL, average_chunk_characters DOUBLE NOT NULL, "
                "category_distribution JSON NOT NULL)"
            )
        finally:
            connection.close()

    def replace_documents(
        self,
        documents: list[RawIntelligenceDocument],
        chunks: list[IntelligenceChunk],
        run: IngestionRun,
    ) -> None:
        self.ensure()
        connection = duckdb.connect(str(self.path))
        try:
            connection.execute("BEGIN TRANSACTION")
            connection.execute("DELETE FROM document_catalogue")
            connection.execute("DELETE FROM document_chunks")
            now = datetime.now(UTC)
            connection.executemany(
                "INSERT INTO document_catalogue VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.document_id,
                        item.title,
                        item.source,
                        item.publication_date,
                        item.document_type,
                        item.product.value,
                        item.region.value,
                        item.segment.value,
                        item.category,
                        item.scenario.value,
                        item.sentiment.value,
                        str(item.file_path),
                        hashlib.sha256(item.content.encode()).hexdigest(),
                        run.dataset_version,
                        run.ingestion_version,
                        now,
                    )
                    for item in documents
                ],
            )
            connection.executemany(
                "INSERT INTO document_chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.chunk_id,
                        item.document_id,
                        item.chunk_index,
                        item.content_hash,
                        len(item.text),
                        run.dataset_version,
                        run.ingestion_version,
                    )
                    for item in chunks
                ],
            )
            connection.execute(
                "DELETE FROM ingestion_runs WHERE ingestion_version = ?",
                [run.ingestion_version],
            )
            connection.execute(
                "INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run.ingestion_version,
                    run.dataset_version,
                    run.embedding_model,
                    run.started_at,
                    run.completed_at,
                    run.document_count,
                    run.chunk_count,
                    run.status,
                ],
            )
            category_counts: dict[str, int] = {}
            for document in documents:
                category_counts[document.category] = category_counts.get(document.category, 0) + 1
            average_chunk_characters = (
                sum(len(chunk.text) for chunk in chunks) / len(chunks) if chunks else 0.0
            )
            connection.execute(
                "INSERT OR REPLACE INTO intelligence_drift_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    run.ingestion_version,
                    now,
                    run.embedding_model,
                    len(documents),
                    len(chunks),
                    average_chunk_characters,
                    json.dumps(category_counts, sort_keys=True),
                ],
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def active_ingestion_version(self) -> str | None:
        if not self.path.exists():
            return None
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            row = connection.execute(
                "SELECT ingestion_version FROM ingestion_runs WHERE status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            connection.close()

    def record_ingestion_run(self, run: IngestionRun) -> None:
        self.ensure()
        connection = duckdb.connect(str(self.path))
        try:
            connection.execute(
                "INSERT OR REPLACE INTO ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run.ingestion_version,
                    run.dataset_version,
                    run.embedding_model,
                    run.started_at,
                    run.completed_at,
                    run.document_count,
                    run.chunk_count,
                    run.status,
                ],
            )
        finally:
            connection.close()

    def filtered_chunk_rows(self, filters: RetrievalFilters) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        clauses = ["d.scenario = ?"]
        values: list[object] = [filters.scenario.value]
        for column, value in (
            ("product", filters.product.value if filters.product else None),
            ("region", filters.region.value if filters.region else None),
            ("segment", filters.segment.value if filters.segment else None),
        ):
            if value is not None:
                clauses.append(f"d.{column} = ?")
                values.append(value)
        if filters.categories:
            placeholders = ", ".join("?" for _ in filters.categories)
            clauses.append(f"d.category IN ({placeholders})")
            values.extend(filters.categories)
        if filters.publication_date_from:
            clauses.append("d.publication_date >= ?")
            values.append(filters.publication_date_from)
        if filters.publication_date_to:
            clauses.append("d.publication_date <= ?")
            values.append(filters.publication_date_to)
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            rows = connection.execute(
                "SELECT c.chunk_id, c.document_id, d.title, d.source, d.publication_date, "
                "d.document_type, d.product, d.region, d.segment, d.category, d.scenario, "
                "d.sentiment, d.file_path, c.ingestion_version FROM document_chunks c "
                "JOIN document_catalogue d USING (document_id) WHERE " + " AND ".join(clauses),
                values,
            ).fetchall()
        finally:
            connection.close()
        fields = (
            "chunk_id",
            "document_id",
            "title",
            "source",
            "publication_date",
            "document_type",
            "product",
            "region",
            "segment",
            "category",
            "scenario",
            "sentiment",
            "file_path",
            "ingestion_version",
        )
        return [dict(zip(fields, row, strict=True)) for row in rows]

    def save_evaluation(self, run_id: str, metrics: dict[str, object]) -> None:
        self.ensure()
        connection = duckdb.connect(str(self.path))
        try:
            connection.execute(
                "INSERT OR REPLACE INTO retrieval_evaluation_runs "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, *metrics.values()],
            )
        finally:
            connection.close()

    def save_recommendation_outcome(self, outcome_id: str, payload: dict[str, object]) -> None:
        self.ensure()
        connection = duckdb.connect(str(self.path))
        try:
            connection.execute(
                "INSERT OR REPLACE INTO recommendation_outcomes VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    outcome_id,
                    payload["recommendation_action"],
                    payload.get("confidence_score"),
                    payload.get("human_review_result"),
                    payload.get("business_outcome"),
                    datetime.now(UTC),
                    json.dumps(payload, sort_keys=True),
                ],
            )
        finally:
            connection.close()
