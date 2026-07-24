from datetime import UTC, date, datetime
from pathlib import Path

from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecision,
    AnalystDecisionType,
    ConfigurationVersions,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)
from pricing_copilot.decisions.store import DecisionStore


def _decision(region: Region = Region.NORTH_WEST) -> AnalystDecision:
    return AnalystDecision(
        record_id="11111111-1111-1111-1111-111111111111",
        question=PortfolioQuestion(
            product=Product.PERSONAL_MOTOR,
            region=region,
            segment=Segment.RENEWAL,
            analysis_period=AnalysisPeriod(
                start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)
            ),
            scenario=None,
        ),
        recommendation=Recommendation(action=RecommendationAction.INCREASE, rationale="test"),
        governance_outcome=GovernanceOutcome(approved=True),
        evidence_ids=["claims-north_west-2025-12-01"],
        decision=AnalystDecisionType.APPROVE,
        rationale="Evidence supports the recommendation.",
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        configuration_versions=ConfigurationVersions(
            model_name="gpt-5.4",
            recommendation_version="single-agent-baseline-v1",
            governance_version="deterministic-governance-v1",
            scenario_seed=20260101,
            scenario_version="v1",
            max_price_movement_pct=5.0,
        ),
    )


def test_save_and_get_round_trips_exactly(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    decision = _decision()
    store.save(decision)

    assert decision.record_id is not None
    loaded = store.get(decision.record_id)
    assert loaded == decision


def test_get_unknown_id_returns_none(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    assert store.get("does-not-exist") is None


def test_list_for_question_filters_by_portfolio(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    nw = _decision(region=Region.NORTH_WEST).model_copy(update={"record_id": "nw-1"})
    se = _decision(region=Region.SOUTH_EAST).model_copy(update={"record_id": "se-1"})
    store.save(nw)
    store.save(se)

    results = store.list_for_question(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    assert [r.record_id for r in results] == ["nw-1"]


def test_decisions_persist_across_store_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "decisions.sqlite3"
    DecisionStore.from_path(db_path).save(_decision())

    reopened = DecisionStore.from_path(db_path)
    assert reopened.get("11111111-1111-1111-1111-111111111111") is not None
