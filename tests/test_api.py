from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pricing_copilot.api import app
from pricing_copilot.contracts import EvidenceDomain
from pricing_copilot.decisions.store import DecisionStore
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.governance_agent import FakeGovernanceAgentRunner
from pricing_copilot.orchestration.pipeline import OrchestrationBundle
from pricing_copilot.orchestration.recommendation_agent import FakeRecommendationAgentRunner
from pricing_copilot.orchestration.specialists import FakeSpecialistAgent, SpecialistAgent

client = TestClient(app)


def _fake_specialist_factory(**_kwargs: Any) -> dict[EvidenceDomain, SpecialistAgent]:
    return {
        domain: FakeSpecialistAgent(SpecialistFindings(summary=f"{domain.value} summary ok"))
        for domain in EvidenceDomain
    }


def _fake_orchestration_bundle(settings: Any) -> OrchestrationBundle:
    return OrchestrationBundle(
        specialist_agents_factory=_fake_specialist_factory,
        recommendation_agent=FakeRecommendationAgentRunner(),
        governance_agent=FakeGovernanceAgentRunner(),
    )


def _patch_default_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        _fake_orchestration_bundle,
    )


def test_health_check() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workflow_endpoint_returns_investigate_for_supported_portfolio() -> None:
    payload = {
        "product": "personal_motor",
        "region": "north_west",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": None,
    }
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["action"] == "investigate"
    assert len(body["missing_evidence"]) == 4


def test_workflow_endpoint_rejects_unsupported_region() -> None:
    payload = {
        "product": "personal_motor",
        "region": "south_east",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": None,
    }
    response = client.post("/workflow", json=payload)
    assert response.status_code == 422
    assert "south_east" in response.json()["detail"]


def test_workflow_endpoint_returns_analytics_for_controlled_increase_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_default_orchestration(monkeypatch)
    payload = {
        "product": "personal_motor",
        "region": "north_west",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": "controlled_increase",
    }
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["missing_evidence"] == []
    assert all(report["status"] == "completed" for report in body["specialist_reports"])
    assert body["analytics"] is not None
    loss_ratio = body["analytics"]["claims"]["loss_ratio"]
    assert loss_ratio["current"] > loss_ratio["baseline"]
    assert body["recommendation"]["action"] == "increase"
    assert body["recommendation"]["price_range"]["upper_pct"] <= 5.0
    assert body["evidence_ledger"] is not None


def _controlled_increase_payload() -> dict[str, Any]:
    return {
        "product": "personal_motor",
        "region": "north_west",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": "controlled_increase",
    }


def _isolated_decision_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    monkeypatch.setattr("pricing_copilot.api.get_decision_store", lambda: store)


def _run_controlled_increase(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _patch_default_orchestration(monkeypatch)
    response = client.post("/workflow", json=_controlled_increase_payload())
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def test_workflow_endpoint_retention_concern_recommends_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_default_orchestration(monkeypatch)
    payload = _controlled_increase_payload()
    payload["scenario"] = "retention_concern"
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["action"] in ("hold", "decrease")
    assert body["missing_evidence"] == []


def test_workflow_endpoint_conflicting_evidence_forces_investigate() -> None:
    payload = _controlled_increase_payload()
    payload["scenario"] = "conflicting_evidence"
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["action"] == "investigate"
    assert body["recommendation"]["price_range"] is None
    assert body["missing_evidence"]


def test_post_decisions_approve_persists_and_is_retrievable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_decision_store(tmp_path, monkeypatch)
    workflow_result = _run_controlled_increase(monkeypatch)
    payload = {
        "question": workflow_result["question"],
        "recommendation": workflow_result["recommendation"],
        "governance_outcome": workflow_result["governance_outcome"],
        "decision": "approve",
        "rationale": "Evidence and citations are sufficient to approve.",
        "conditions": [],
    }
    response = client.post("/decisions", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["record_id"]
    assert body["decision"] == "approve"

    fetched = client.get(f"/decisions/{body['record_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["record_id"] == body["record_id"]


def test_post_decisions_rejects_missing_rationale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_decision_store(tmp_path, monkeypatch)
    workflow_result = _run_controlled_increase(monkeypatch)
    payload = {
        "question": workflow_result["question"],
        "recommendation": workflow_result["recommendation"],
        "governance_outcome": workflow_result["governance_outcome"],
        "decision": "approve",
        "rationale": "   ",
        "conditions": [],
    }
    response = client.post("/decisions", json=payload)
    assert response.status_code == 422


def test_post_decisions_approve_with_conditions_requires_conditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_decision_store(tmp_path, monkeypatch)
    workflow_result = _run_controlled_increase(monkeypatch)
    payload = {
        "question": workflow_result["question"],
        "recommendation": workflow_result["recommendation"],
        "governance_outcome": workflow_result["governance_outcome"],
        "decision": "approve_with_conditions",
        "rationale": "Approve but constrain the rollout.",
        "conditions": [],
    }
    response = client.post("/decisions", json=payload)
    assert response.status_code == 422


def test_get_decisions_unknown_id_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_decision_store(tmp_path, monkeypatch)
    response = client.get("/decisions/does-not-exist")
    assert response.status_code == 404


def test_recording_a_decision_never_mutates_subsequent_workflow_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_decision_store(tmp_path, monkeypatch)
    before = _run_controlled_increase(monkeypatch)
    payload = {
        "question": before["question"],
        "recommendation": before["recommendation"],
        "governance_outcome": before["governance_outcome"],
        "decision": "reject",
        "rationale": "Not convinced the evidence supports action yet.",
        "conditions": [],
    }
    decision_response = client.post("/decisions", json=payload)
    assert decision_response.status_code == 200

    after = _run_controlled_increase(monkeypatch)
    assert after["analytics"] == before["analytics"]
    assert after["recommendation"]["action"] == before["recommendation"]["action"]
