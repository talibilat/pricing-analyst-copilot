from __future__ import annotations

import re

from pricing_copilot.contracts import PriceRange
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.models import EvidenceLedger
from pricing_copilot.recommendation.contracts import RecommendationDraft

GOVERNANCE_VERSION = "deterministic-governance-v1"

_NUMBER_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
# Wide enough to tolerate natural-language rounding of a precise figure (a model saying
# "around 70%" for a real 71.1% is a faithful paraphrase, not a fabrication) while still
# catching genuinely invented figures - order-of-magnitude or category-wrong numbers land
# far outside this margin.
_TOLERANCE = 5.0

_EXECUTION_CLAIM_PATTERN = re.compile(
    r"\bprice (?:has been|was|is being) (?:changed|increased|decreased|adjusted)\b"
    r"|\b(?:already |has )?(?:implemented|executed|applied) (?:the|this) "
    r"(?:price|increase|decrease)\b"
    r"|\baction (?:has been|was) taken\b",
    re.IGNORECASE,
)


def _check_no_execution_claim_language(texts: list[str]) -> None:
    for text in texts:
        if _EXECUTION_CLAIM_PATTERN.search(text):
            raise RecommendationValidationError(
                "Recommendation text claims an executed price change, which this system must "
                "never do - it is decision support only."
            )


_CAUSAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bcaused\b", "coincided with"),
    (r"\bcauses\b", "coincides with"),
    (r"\bcausing\b", "coinciding with"),
    (r"\bled to\b", "was associated with"),
    (r"\bleads to\b", "is associated with"),
    (r"\bresulted in\b", "was followed by"),
    (r"\bresults in\b", "is followed by"),
    (r"\bdrove\b", "coincided with"),
    (r"\bdrives\b", "coincides with"),
    (r"\bdue to\b", "alongside"),
)


def _soften_causal_language(text: str) -> str:
    softened = text
    for pattern, replacement in _CAUSAL_REPLACEMENTS:
        softened = re.sub(pattern, replacement, softened, flags=re.IGNORECASE)
    return softened


class RecommendationValidationError(ValueError):
    """Raised when a recommendation draft fails deterministic governance checks."""


def _allowed_numbers(
    ledger: EvidenceLedger,
    documents: list[RetrievedDocument],
    price_range: PriceRange | None,
    max_movement_pct: float,
) -> set[float]:
    numbers = {round(max_movement_pct, 1), round(-max_movement_pct, 1)}
    if price_range is not None:
        numbers.add(round(price_range.lower_pct, 1))
        numbers.add(round(price_range.upper_pct, 1))
    percentage_metrics = {"loss_ratio", "quote_to_sale_conversion", "renewal_retention"}
    for entry in ledger.entries:
        for raw in (entry.value, entry.baseline_value):
            if raw is None:
                continue
            if entry.metric_name in percentage_metrics:
                numbers.add(round(raw * 100, 1))
            else:
                numbers.add(round(raw, 1))
    # Cited unstructured evidence (retrieved document text) may state figures - such as
    # "reduced pricing by four to six percent" - that a faithful paraphrase can render in
    # digit form. Those are legitimately supported, so scan document bodies too.
    for retrieved in documents:
        for match in _NUMBER_PATTERN.finditer(retrieved.document.body):
            numbers.add(round(float(match.group(1)), 1))
    return numbers


def validate_and_clamp_draft(
    draft: RecommendationDraft,
    *,
    ledger: EvidenceLedger,
    documents: list[RetrievedDocument],
    max_movement_pct: float,
) -> RecommendationDraft:
    known_ids = ledger.ids()
    unknown_ids = [eid for eid in draft.cited_evidence_ids if eid not in known_ids]
    if unknown_ids:
        raise RecommendationValidationError(
            f"Recommendation cites unknown evidence ids: {unknown_ids}"
        )

    _check_no_execution_claim_language(
        [draft.rationale, *draft.counter_evidence, *draft.conditions, *draft.investigation_areas]
    )

    price_range = draft.price_range
    conditions = list(draft.conditions)
    if price_range is not None:
        clamped_lower = max(-max_movement_pct, min(price_range.lower_pct, max_movement_pct))
        clamped_upper = max(-max_movement_pct, min(price_range.upper_pct, max_movement_pct))
        if clamped_lower != price_range.lower_pct or clamped_upper != price_range.upper_pct:
            conditions.append(
                f"Proposed range clamped to the configured +/-{max_movement_pct:g}% policy limit."
            )
            price_range = PriceRange(lower_pct=clamped_lower, upper_pct=clamped_upper)

    allowed_numbers = _allowed_numbers(ledger, documents, price_range, max_movement_pct)
    for text in [draft.rationale, *draft.counter_evidence, *conditions, *draft.investigation_areas]:
        for match in _NUMBER_PATTERN.finditer(text):
            value = float(match.group(1))
            if not any(abs(value - allowed) <= _TOLERANCE for allowed in allowed_numbers):
                raise RecommendationValidationError(
                    f"Recommendation text cites an unsupported figure: {value}% "
                    f"(known values: {sorted(allowed_numbers)})"
                )

    return draft.model_copy(
        update={
            "price_range": price_range,
            "conditions": conditions,
            "rationale": _soften_causal_language(draft.rationale),
            "counter_evidence": [_soften_causal_language(t) for t in draft.counter_evidence],
            "investigation_areas": [
                _soften_causal_language(t) for t in draft.investigation_areas
            ],
        }
    )
