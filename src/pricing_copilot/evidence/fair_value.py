from __future__ import annotations

from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.documents.corpus import DocumentSentiment
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.models import FairValueStatus

MATERIAL_RETENTION_DROP_PCT = -10.0


def calculate_fair_value_status(
    *,
    action: RecommendationAction,
    conversion_movement_pct: float | None,
    documents: list[RetrievedDocument],
) -> tuple[FairValueStatus, list[str]]:
    if action is not RecommendationAction.INCREASE:
        return FairValueStatus.NO_CONCERN, []

    movement = conversion_movement_pct or 0.0
    against_count = sum(
        1 for r in documents if r.document.sentiment == DocumentSentiment.AGAINST_INCREASE
    )

    if against_count >= 2 or movement < MATERIAL_RETENTION_DROP_PCT:
        return FairValueStatus.CONCERN_IDENTIFIED, [
            "Escalate to fair-value review before any rollout: evidence flags material price "
            "sensitivity."
        ]

    return FairValueStatus.REVIEW_RECOMMENDED, [
        "Confirm no disproportionate impact on price-sensitive segments before rollout.",
        "Monitor retention for two renewal cycles after implementation.",
    ]
