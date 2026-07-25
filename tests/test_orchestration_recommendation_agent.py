import asyncio
import inspect

from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.evidence.models import EvidenceLedger, EvidenceLedgerEntry
from pricing_copilot.orchestration.recommendation_agent import (
    FakeRecommendationAgentRunner,
    RecommendationAgentRunner,
)


def test_synthesize_signature_has_no_raw_analytics_or_documents_parameter() -> None:
    parameters = set(inspect.signature(RecommendationAgentRunner.synthesize).parameters)
    assert "analytics" not in parameters
    assert "documents" not in parameters
    assert {"specialist_reports", "ledger"}.issubset(parameters)


def _ledger(loss_ratio_movement: float, retention_movement: float) -> EvidenceLedger:
    return EvidenceLedger(
        entries=[
            EvidenceLedgerEntry(
                evidence_id="claims-x",
                source_type="structured_metric",
                source_reference="claims",
                metric_name="loss_ratio",
                value=0.71 * (1 + loss_ratio_movement / 100),
                baseline_value=0.71,
                interpretation="Loss ratio moved.",
            ),
            EvidenceLedgerEntry(
                evidence_id="conversion-x",
                source_type="structured_metric",
                source_reference="conversion",
                metric_name="renewal_retention",
                value=0.80 * (1 + retention_movement / 100),
                baseline_value=0.80,
                interpretation="Retention moved.",
            ),
        ]
    )


def test_fake_recommendation_agent_holds_when_retention_drops_without_loss_ratio_rise() -> None:
    runner = FakeRecommendationAgentRunner()
    draft = asyncio.run(
        runner.synthesize(specialist_reports=[], ledger=_ledger(0.0, -8.0), max_movement_pct=5.0)
    )
    assert draft.action is RecommendationAction.HOLD


def test_fake_recommendation_agent_increases_when_loss_ratio_rises() -> None:
    runner = FakeRecommendationAgentRunner()
    draft = asyncio.run(
        runner.synthesize(specialist_reports=[], ledger=_ledger(15.0, 0.0), max_movement_pct=5.0)
    )
    assert draft.action is RecommendationAction.INCREASE
