import json
from datetime import date
from pathlib import Path

from pricing_copilot.contracts import (
    AnalysisPeriod,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
    WorkflowResult,
)
from pricing_copilot.recommendation.trace import load_baseline_trace, save_baseline_trace


def _result() -> WorkflowResult:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=None,
    )
    return WorkflowResult(
        question=question,
        specialist_reports=[],
        recommendation=Recommendation(action=RecommendationAction.HOLD, rationale="test"),
        governance_outcome=GovernanceOutcome(approved=True),
        missing_evidence=[],
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    result = _result()
    trace_path = tmp_path / "trace.json"

    save_baseline_trace(result, trace_path)

    assert trace_path.exists()
    raw = json.loads(trace_path.read_text())
    assert raw["recommendation"]["action"] == "hold"

    loaded = load_baseline_trace(trace_path)
    assert loaded.recommendation.action is RecommendationAction.HOLD
    assert loaded.question.product is Product.PERSONAL_MOTOR
