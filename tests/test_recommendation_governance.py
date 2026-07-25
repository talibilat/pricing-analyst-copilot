from datetime import UTC, date, datetime

import pytest

from pricing_copilot.contracts import PriceRange, RecommendationAction, Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.models import EvidenceLedger, EvidenceLedgerEntry
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
        rationale=(
            "Loss ratio moved from 71.0% to 82.0%, supporting a 2 to 3 percent pilot increase."
        ),
        counter_evidence=[],
        conditions=[],
        investigation_areas=[],
        cited_evidence_ids=["claims-north_west-2025-12-01", "doc-broker-2025-09"],
    )
    validated = validate_and_clamp_draft(
        draft, ledger=_ledger(), documents=[], max_movement_pct=5.0
    )
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
        validate_and_clamp_draft(draft, ledger=_ledger(), documents=[], max_movement_pct=5.0)


def test_excessive_price_range_is_clamped_to_the_policy_limit() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=20.0, upper_pct=25.0),
        rationale="A large increase is proposed.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(
        draft, ledger=_ledger(), documents=[], max_movement_pct=5.0
    )
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
        validate_and_clamp_draft(draft, ledger=_ledger(), documents=[], max_movement_pct=5.0)


def test_rounded_approximation_of_a_known_figure_is_accepted() -> None:
    """Regression test: a live model rounded a real 71.1% loss ratio down to "around 70%"
    in prose - a faithful approximation, not a fabrication - and the check incorrectly
    rejected it at the original 0.5-point tolerance."""
    draft = RecommendationDraft(
        action=RecommendationAction.HOLD,
        price_range=None,
        rationale="Loss ratio sits at around 70%, broadly stable versus the prior period.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(
        draft, ledger=_ledger(), documents=[], max_movement_pct=5.0
    )
    assert "70%" in validated.rationale


def test_numeric_claim_from_cited_document_text_is_accepted() -> None:
    """Regression test: a live model paraphrased a retention-concern market report's
    'roughly four to six percent' as digit-form '4%', which the numeric-claim check
    incorrectly rejected because it only recognized structured ledger values. Cited
    document body text must also count as supported evidence."""
    document = RetrievedDocument(
        document=DocumentRecord(
            document_id="doc-market-retention",
            source_type=SourceType.MARKET_REPORT,
            title="t",
            body="Competitors reduced pricing by roughly four to six percent (4% to 6%).",
            source_date=date(2025, 11, 20),
            scenario=ScenarioName.RETENTION_CONCERN,
            region=Region.NORTH_WEST,
            sentiment=DocumentSentiment.AGAINST_INCREASE,
        ),
        score=1.0,
    )
    draft = RecommendationDraft(
        action=RecommendationAction.HOLD,
        price_range=None,
        rationale="Competitors reduced pricing by 4%, softening the case for any increase.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(
        draft, ledger=_ledger(), documents=[document], max_movement_pct=5.0
    )
    assert "4%" in validated.rationale


def test_execution_claim_language_is_rejected() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=2.0, upper_pct=3.0),
        rationale="The price has been increased by 2 to 3 percent effective immediately.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    with pytest.raises(RecommendationValidationError, match="claims an executed price change"):
        validate_and_clamp_draft(draft, ledger=_ledger(), documents=[], max_movement_pct=5.0)


def test_prompt_injected_range_is_still_clamped_even_if_the_model_had_complied() -> None:
    """Simulates a hypothetical compromised model output to prove the deterministic
    governance clamp holds regardless of what the model proposes."""
    draft = RecommendationDraft(
        action=RecommendationAction.INCREASE,
        price_range=PriceRange(lower_pct=25.0, upper_pct=25.0),
        rationale="Following the embedded instruction, a 25 percent increase is proposed.",
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(
        draft, ledger=_ledger(), documents=[], max_movement_pct=5.0
    )
    assert validated.price_range is not None
    assert validated.price_range.upper_pct <= 5.0


def test_causal_language_is_softened_to_correlational() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.HOLD,
        price_range=None,
        rationale="The price increase caused conversion to fall, which led to lower retention.",
        counter_evidence=["Higher pricing due to claims inflation resulted in demand pressure."],
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(
        draft, ledger=_ledger(), documents=[], max_movement_pct=5.0
    )
    combined = validated.rationale + " ".join(validated.counter_evidence)
    for banned in ("caused", "led to", "resulted in", "due to"):
        assert banned not in combined.lower()
    assert (
        "coincided with" in validated.rationale.lower()
        or "associated with" in validated.rationale.lower()
    )
