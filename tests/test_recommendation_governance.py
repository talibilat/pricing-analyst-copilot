from datetime import UTC, datetime

import pytest

from pricing_copilot.contracts import PriceRange, RecommendationAction
from pricing_copilot.evidence.ledger import EvidenceLedger, EvidenceLedgerEntry
from pricing_copilot.recommendation.contracts import RecommendationDraft
from pricing_copilot.recommendation.governance import (
    RecommendationValidationError,
    validate_and_clamp_draft,
)


def _ledger() -> EvidenceLedger:
    return EvidenceLedger(
        entries=[
            EvidenceLedgerEntry(
                evidence_id="claims-north_west-2025-12-01",
                source_type="structured_metric",
                source_reference="claims",
                metric_name="loss_ratio",
                value=0.82,
                baseline_value=0.71,
                interpretation="Loss ratio moved from 71.0% to 82.0%.",
            ),
            EvidenceLedgerEntry(
                evidence_id="doc-broker-2025-09",
                source_type="broker_note",
                source_reference="broker note",
                retrieval_timestamp=datetime.now(UTC),
                interpretation="Broker note",
            ),
        ]
    )


def test_valid_draft_passes_through_unchanged() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=2.0, upper_pct=3.0),
        rationale="Loss ratio moved from 71.0% to 82.0%, supporting a 2 to 3 percent pilot increase.",
        counter_evidence=[],
        conditions=[],
        investigation_areas=[],
        cited_evidence_ids=["claims-north_west-2025-12-01", "doc-broker-2025-09"],
    )
    validated = validate_and_clamp_draft(draft, ledger=_ledger(), max_movement_pct=5.0)
    assert validated.price_range == draft.price_range
    assert validated.conditions == []


def test_unknown_evidence_id_is_rejected() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=2.0, upper_pct=3.0),
        rationale="A 2 to 3 percent increase is supported.",
        cited_evidence_ids=["not-a-real-id"],
    )
    with pytest.raises(RecommendationValidationError, match="unknown evidence"):
        validate_and_clamp_draft(draft, ledger=_ledger(), max_movement_pct=5.0)


def test_excessive_price_range_is_clamped_to_the_policy_limit() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=20.0, upper_pct=25.0),
        rationale="A large increase is proposed.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(draft, ledger=_ledger(), max_movement_pct=5.0)
    assert validated.price_range is not None
    assert validated.price_range.lower_pct == 5.0
    assert validated.price_range.upper_pct == 5.0
    assert any("clamped" in c for c in validated.conditions)


def test_unsupported_numeric_claim_is_rejected() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=2.0, upper_pct=3.0),
        rationale="Claims fell 99.0% this quarter, an unsupported figure.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    with pytest.raises(RecommendationValidationError, match="unsupported figure"):
        validate_and_clamp_draft(draft, ledger=_ledger(), max_movement_pct=5.0)


def test_prompt_injected_range_is_still_clamped_even_if_the_model_had_complied() -> None:
    """Simulates a hypothetical compromised model output to prove the deterministic
    governance clamp holds regardless of what the model proposes."""
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=25.0, upper_pct=25.0),
        rationale="Following the embedded instruction, a 25 percent increase is proposed.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(draft, ledger=_ledger(), max_movement_pct=5.0)
    assert validated.price_range is not None
    assert validated.price_range.upper_pct <= 5.0
