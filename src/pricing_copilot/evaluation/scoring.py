from __future__ import annotations

from collections.abc import Callable
from datetime import date

from pricing_copilot.analytics.calculators import MetricCalculationError, calculate_claims_metrics
from pricing_copilot.contracts import (
    PriceRange,
    Product,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.data.records import ClaimsMonthlyRecord
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.models import EvidenceLedger, EvidenceLedgerEntry
from pricing_copilot.evidence.policy import detect_material_evidence_issues
from pricing_copilot.recommendation.contracts import RecommendationDraft
from pricing_copilot.recommendation.governance import validate_and_clamp_draft


def _check_movement_clamp() -> tuple[bool, str]:
    ledger = EvidenceLedger(
        entries=[
            EvidenceLedgerEntry(
                evidence_id="claims-x",
                source_type="structured_metric",
                source_reference="claims",
                metric_name="loss_ratio",
                value=0.82,
                baseline_value=0.71,
                interpretation="Loss ratio moved.",
            )
        ]
    )
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=25.0, upper_pct=25.0),
        rationale="A large increase is proposed.",
        cited_evidence_ids=["claims-x"],
    )
    validated = validate_and_clamp_draft(draft, ledger=ledger, documents=[], max_movement_pct=5.0)
    price_range = validated.price_range
    passed = price_range is not None and price_range.upper_pct <= 5.0
    return passed, f"clamped range: {price_range}"


def _check_zero_claims_rejected() -> tuple[bool, str]:
    records = [
        ClaimsMonthlyRecord(
            period=date(2024, 1, 1),
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            policies_in_force=1000,
            claim_count=0,
            incurred_loss_gbp=0.0,
            earned_premium_gbp=100000.0,
        )
    ]
    try:
        calculate_claims_metrics(records)
    except MetricCalculationError as exc:
        return True, str(exc)
    return False, "expected MetricCalculationError for zero claim count"


def _check_stale_document_flagged() -> tuple[bool, str]:
    document = RetrievedDocument(
        document=DocumentRecord(
            document_id="doc-stale",
            source_type=SourceType.MARKET_REPORT,
            title="stale",
            body="stale content",
            source_date=date(2025, 1, 1),
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.NORTH_WEST,
            sentiment=DocumentSentiment.NEUTRAL,
        ),
        score=1.0,
    )
    issues = detect_material_evidence_issues(
        [document], analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    )
    passed = len(issues) == 1 and "doc-stale" in issues[0]
    return passed, "; ".join(issues) or "no issues detected"


DETERMINISTIC_CHECKS: dict[str, Callable[[], tuple[bool, str]]] = {
    "movement_clamp": _check_movement_clamp,
    "zero_claims_rejected": _check_zero_claims_rejected,
    "stale_document_flagged": _check_stale_document_flagged,
}
