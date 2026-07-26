from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from openai import OpenAI
from qdrant_client import QdrantClient, models

from pricing_copilot.config import AzureOpenAISettings, Settings, azure_openai_base_url
from pricing_copilot.intelligence.chunking import chunk_document
from pricing_copilot.intelligence.contracts import IngestionRun, RawIntelligenceDocument
from pricing_copilot.intelligence.store import IntelligenceCatalogue

EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDDING_DIMENSIONS = 1_536
EMBEDDING_BATCH_SIZE = 64


class EmbeddingClient(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class AzureOpenAIEmbeddingClient:
    """Azure OpenAI embedding client using the configured deployment name."""

    def __init__(self, azure: AzureOpenAISettings) -> None:
        if not azure.api_key or not azure.endpoint:
            raise RuntimeError(
                "Azure OpenAI embeddings are not configured "
                "(set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env)."
            )
        self.model_name = azure.embeddings_deployment
        self._client = OpenAI(
            api_key=azure.api_key,
            base_url=azure_openai_base_url(azure.endpoint),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self.model_name, input=texts)
        return [list(item.embedding) for item in response.data]


def load_raw_documents(directory: Path) -> list[RawIntelligenceDocument]:
    documents: list[RawIntelligenceDocument] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        if not isinstance(payload, list):
            raise ValueError(f"Unstructured source {path} must contain a JSON array.")
        documents.extend(
            RawIntelligenceDocument.model_validate({**item, "file_path": path}) for item in payload
        )
    ids = [item.document_id for item in documents]
    if not documents:
        raise ValueError(f"No raw intelligence JSON files found in {directory}.")
    if len(ids) != len(set(ids)):
        raise ValueError("Raw intelligence document IDs must be unique.")
    return documents


def _payload(
    document: RawIntelligenceDocument, chunk_id: str, text: str, version: str
) -> dict[str, str]:
    return {
        "document_id": document.document_id,
        "chunk_id": chunk_id,
        "title": document.title,
        "source": document.source,
        "publication_date": document.publication_date.isoformat(),
        "document_type": document.document_type,
        "product": document.product.value,
        "region": document.region.value,
        "segment": document.segment.value,
        "category": document.category,
        "scenario": document.scenario.value,
        "sentiment": document.sentiment.value,
        "file_path": str(document.file_path),
        "text": text,
        "ingestion_version": version,
    }


def _collection(client: QdrantClient, settings: Settings) -> None:
    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIMENSIONS,
                distance=models.Distance.COSINE,
            ),
        )


def ingest_market_intelligence(
    settings: Settings,
    *,
    embedding_client: EmbeddingClient | None = None,
) -> IngestionRun:
    """Load raw files, chunk them, embed them, and atomically replace the local index."""
    documents = load_raw_documents(settings.market_intelligence_raw_directory)
    embedder = embedding_client or AzureOpenAIEmbeddingClient(AzureOpenAISettings())
    if embedder.model_name != EMBEDDING_MODEL:
        # Azure deployment names can differ. The configured deployment is still recorded,
        # while the expected Ada embedding dimensionality remains a hard compatibility check.
        embedding_model = embedder.model_name
    else:
        embedding_model = EMBEDDING_MODEL
    all_chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document.document_id, document.content)
    ]
    started_at = datetime.now(UTC)
    run = IngestionRun(
        ingestion_version=f"ingest-{uuid4().hex}",
        dataset_version=settings.market_intelligence_dataset_version,
        embedding_model=embedding_model,
        started_at=started_at,
        document_count=len(documents),
        chunk_count=len(all_chunks),
        status="running",
    )
    document_by_id = {item.document_id: item for item in documents}
    client = QdrantClient(path=str(settings.qdrant_path))
    try:
        if client.collection_exists(settings.qdrant_collection):
            client.delete_collection(settings.qdrant_collection)
        _collection(client, settings)
        for start in range(0, len(all_chunks), EMBEDDING_BATCH_SIZE):
            batch = all_chunks[start : start + EMBEDDING_BATCH_SIZE]
            vectors = embedder.embed([item.text for item in batch])
            invalid_dimensions = any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors)
            if len(vectors) != len(batch) or invalid_dimensions:
                raise ValueError(
                    f"Azure embedding deployment {embedding_model!r} must return "
                    f"{EMBEDDING_DIMENSIONS}-dimension vectors for text-embedding-ada-002."
                )
            client.upsert(
                collection_name=settings.qdrant_collection,
                points=[
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, item.chunk_id)),
                        vector=vector,
                        payload=_payload(
                            document_by_id[item.document_id],
                            item.chunk_id,
                            item.text,
                            run.ingestion_version,
                        ),
                    )
                    for item, vector in zip(batch, vectors, strict=True)
                ],
                wait=True,
            )
        run = run.model_copy(update={"completed_at": datetime.now(UTC), "status": "completed"})
        IntelligenceCatalogue(settings.market_intelligence_database_path).replace_documents(
            documents, all_chunks, run
        )
        return run
    except Exception:
        failed = run.model_copy(update={"completed_at": datetime.now(UTC), "status": "failed"})
        IntelligenceCatalogue(settings.market_intelligence_database_path).record_ingestion_run(
            failed
        )
        raise
    finally:
        client.close()


class DeterministicEmbeddingClient:
    """Credential-free 1,536-dimensional embedder reserved for automated tests."""

    model_name = EMBEDDING_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha512(text.encode()).digest()
            vectors.append(
                [digest[index % len(digest)] / 255 for index in range(EMBEDDING_DIMENSIONS)]
            )
        return vectors
