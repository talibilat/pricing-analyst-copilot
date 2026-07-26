from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles
from time import perf_counter
from uuid import uuid4

from pricing_copilot.config import Settings
from pricing_copilot.intelligence.contracts import (
    RetrievalEvaluationCase,
    RetrievalEvaluationMetrics,
)
from pricing_copilot.intelligence.retrieval import HybridRetriever
from pricing_copilot.intelligence.store import IntelligenceCatalogue


def load_retrieval_cases(path: Path) -> list[RetrievalEvaluationCase]:
    return [
        RetrievalEvaluationCase.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def evaluate_retrieval(
    settings: Settings,
    retriever: HybridRetriever,
    *,
    cases_path: Path,
    top_k: int = 6,
) -> RetrievalEvaluationMetrics:
    cases = load_retrieval_cases(cases_path)
    recalls: list[float] = []
    precisions: list[float] = []
    metadata_hits: list[float] = []
    citations: list[float] = []
    unsupported: list[float] = []
    latencies: list[float] = []
    for case in cases:
        started = perf_counter()
        evidence, _ = retriever.retrieve(
            case.user_question, case.required_metadata_filters, top_k=top_k
        )
        latencies.append((perf_counter() - started) * 1000)
        expected_ids = set(case.expected_document_ids)
        returned_ids = {item.document_id for item in evidence}
        relevant = returned_ids & expected_ids
        recalls.append(len(relevant) / len(expected_ids) if expected_ids else 1.0)
        precisions.append(len(relevant) / len(returned_ids) if returned_ids else 0.0)
        filters = case.required_metadata_filters
        metadata_hits.append(
            float(
                all(
                    item.scenario is filters.scenario
                    and (filters.product is None or item.product is filters.product)
                    and (filters.region is None or item.region is filters.region)
                    and (filters.segment is None or item.segment is filters.segment)
                    and (not filters.categories or item.category in filters.categories)
                    and (
                        filters.publication_date_from is None
                        or item.publication_date >= filters.publication_date_from
                    )
                    and (
                        filters.publication_date_to is None
                        or item.publication_date <= filters.publication_date_to
                    )
                    for item in evidence
                )
            )
        )
        citations.append(float(all(item.document_id and item.chunk_id for item in evidence)))
        unsupported.append(
            sum(1 for item in evidence if item.document_id not in expected_ids) / len(evidence)
            if evidence
            else 0.0
        )
    p95 = max(latencies) if len(latencies) < 2 else quantiles(latencies, n=20)[18]
    metrics = RetrievalEvaluationMetrics(
        evaluated_at=datetime.now(UTC),
        dataset_version=settings.market_intelligence_dataset_version,
        recall_at_k=round(sum(recalls) / len(recalls), 4),
        precision_at_k=round(sum(precisions) / len(precisions), 4),
        metadata_filter_accuracy=round(sum(metadata_hits) / len(metadata_hits), 4),
        citation_correctness=round(sum(citations) / len(citations), 4),
        unsupported_claim_rate=round(sum(unsupported) / len(unsupported), 4),
        retrieval_latency_ms_p95=round(p95, 2),
    )
    IntelligenceCatalogue(settings.market_intelligence_database_path).save_evaluation(
        f"retrieval-eval-{uuid4().hex}",
        metrics.model_dump(),
    )
    return metrics


def append_agent_trace(path: Path, payload: dict[str, object]) -> None:
    """Append a privacy-safe agent trace envelope with evidence references only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
