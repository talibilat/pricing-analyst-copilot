from __future__ import annotations

import re

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, documents_for_scenario

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class RetrievedDocument(BaseModel):
    document: DocumentRecord
    score: float


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def retrieve_documents(
    *, scenario: ScenarioName, region: Region, query: str, top_k: int = 6
) -> list[RetrievedDocument]:
    candidates = documents_for_scenario(scenario, region)
    if not candidates:
        return []

    corpus_tokens = [_tokenize(f"{d.title} {d.body}") for d in candidates]
    bm25 = BM25Okapi(corpus_tokens)
    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [RetrievedDocument(document=doc, score=float(score)) for doc, score in ranked[:top_k]]
