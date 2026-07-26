from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.documents.corpus import DocumentSentiment, SourceType


class RawIntelligenceDocument(BaseModel):
    document_id: str
    title: str
    source: str
    publication_date: date
    document_type: str
    product: Product
    region: Region
    segment: Segment
    category: str
    sentiment: DocumentSentiment
    scenario: ScenarioName
    content: str = Field(min_length=1)
    file_path: Path


class IntelligenceChunk(BaseModel):
    document_id: str
    chunk_id: str
    chunk_index: int
    text: str
    content_hash: str


class IngestionRun(BaseModel):
    ingestion_version: str
    dataset_version: str
    embedding_model: str
    started_at: datetime
    completed_at: datetime | None = None
    document_count: int = 0
    chunk_count: int = 0
    status: str


class RetrievalFilters(BaseModel):
    scenario: ScenarioName
    product: Product | None = None
    region: Region | None = None
    segment: Segment | None = None
    categories: list[str] = Field(default_factory=list)
    publication_date_from: date | None = None
    publication_date_to: date | None = None


class RetrievedEvidence(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    source: str
    publication_date: date
    document_type: str
    category: str
    sentiment: DocumentSentiment
    product: Product
    region: Region
    segment: Segment
    scenario: ScenarioName
    file_path: str
    relevant_text: str
    retrieval_score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    ingestion_version: str


class RetrievalEvaluationCase(BaseModel):
    case_id: str
    user_question: str
    expected_document_ids: list[str]
    expected_categories: list[str]
    required_metadata_filters: RetrievalFilters


class RetrievalEvaluationMetrics(BaseModel):
    evaluated_at: datetime
    dataset_version: str
    recall_at_k: float
    precision_at_k: float
    metadata_filter_accuracy: float
    citation_correctness: float
    unsupported_claim_rate: float
    retrieval_latency_ms_p95: float


def source_type_for_document_type(document_type: str) -> SourceType:
    if document_type in {"repair_cost_inflation_report"}:
        return SourceType.REPAIR_COST_REPORT
    if document_type.endswith("summary") or document_type == "call_centre_transcript_summary":
        return SourceType.CUSTOMER_FEEDBACK
    if document_type == "broker_note":
        return SourceType.BROKER_NOTE
    return SourceType.MARKET_REPORT
