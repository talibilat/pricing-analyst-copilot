from pathlib import Path

import duckdb

from pricing_copilot.config import Settings
from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.intelligence.contracts import RetrievalFilters
from pricing_copilot.intelligence.evaluation import evaluate_retrieval
from pricing_copilot.intelligence.ingestion import (
    DeterministicEmbeddingClient,
    ingest_market_intelligence,
)
from pricing_copilot.intelligence.retrieval import HybridRetriever


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        market_intelligence_database_path=tmp_path / "market_intelligence.duckdb",
        qdrant_path=tmp_path / "qdrant",
        market_intelligence_raw_directory=Path("data/unstructured"),
    )


def test_ingestion_creates_isolated_catalogue_and_local_qdrant_index(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    run = ingest_market_intelligence(settings, embedding_client=DeterministicEmbeddingClient())

    assert run.status == "completed"
    assert run.document_count == 19
    assert run.chunk_count >= run.document_count
    assert settings.market_intelligence_database_path.exists()
    assert settings.qdrant_path.exists()

    connection = duckdb.connect(str(settings.market_intelligence_database_path), read_only=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM document_catalogue").fetchone() == (19,)
        chunk_count = connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()
        assert chunk_count is not None
        assert chunk_count[0] >= 19
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM intelligence_drift_metrics").fetchone() == (
            1,
        )
    finally:
        connection.close()


def test_hybrid_retrieval_preserves_chunk_citations_and_metadata_filters(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ingest_market_intelligence(settings, embedding_client=DeterministicEmbeddingClient())
    retriever = HybridRetriever(settings, DeterministicEmbeddingClient())

    evidence, _ = retriever.retrieve(
        "repair cost inflation claims severity",
        RetrievalFilters(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
        ),
        top_k=6,
    )

    assert evidence
    assert all(item.document_id and item.chunk_id and item.relevant_text for item in evidence)
    assert all(item.scenario is ScenarioName.CONTROLLED_INCREASE for item in evidence)
    assert all(item.product is Product.PERSONAL_MOTOR for item in evidence)
    assert any(item.document_id == "mi-controlled-repair-2025-10" for item in evidence)


def test_hybrid_retrieval_applies_category_filter_before_ranking(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ingest_market_intelligence(settings, embedding_client=DeterministicEmbeddingClient())
    retriever = HybridRetriever(settings, DeterministicEmbeddingClient())

    evidence, _ = retriever.retrieve(
        "repair costs and severity",
        RetrievalFilters(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            categories=["claims_cost"],
        ),
        top_k=6,
    )

    assert evidence
    assert {item.category for item in evidence} == {"claims_cost"}
    assert {item.document_id for item in evidence} == {"mi-controlled-repair-2025-10"}


def test_retrieval_evaluation_records_requested_metrics(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ingest_market_intelligence(settings, embedding_client=DeterministicEmbeddingClient())
    metrics = evaluate_retrieval(
        settings,
        HybridRetriever(settings, DeterministicEmbeddingClient()),
        cases_path=Path("data/evaluation/retrieval_cases.jsonl"),
    )

    assert 0.0 <= metrics.recall_at_k <= 1.0
    assert 0.0 <= metrics.precision_at_k <= 1.0
    assert metrics.metadata_filter_accuracy == 1.0
    assert metrics.citation_correctness == 1.0
    assert metrics.retrieval_latency_ms_p95 >= 0.0
