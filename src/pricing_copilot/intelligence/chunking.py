from __future__ import annotations

import hashlib
import re

from pricing_copilot.intelligence.contracts import IntelligenceChunk

MAX_CHUNK_CHARACTERS = 1_200
OVERLAP_CHARACTERS = 160


def chunk_document(document_id: str, content: str) -> list[IntelligenceChunk]:
    """Split on Markdown paragraphs first, with a bounded character overlap.

    The 1,200-character bound is intentionally far below the embedding model's
    token limit, and the overlap preserves context around paragraph boundaries.
    """
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= MAX_CHUNK_CHARACTERS:
            current = candidate
            continue
        if current:
            pieces.append(current)
        while len(paragraph) > MAX_CHUNK_CHARACTERS:
            pieces.append(paragraph[:MAX_CHUNK_CHARACTERS])
            paragraph = paragraph[MAX_CHUNK_CHARACTERS - OVERLAP_CHARACTERS :]
        current = paragraph
    if current:
        pieces.append(current)

    return [
        IntelligenceChunk(
            document_id=document_id,
            chunk_id=f"{document_id}:chunk-{index:03d}",
            chunk_index=index,
            text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(pieces, start=1)
    ]
