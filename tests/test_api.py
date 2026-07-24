from fastapi.testclient import TestClient

from pricing_copilot.api import app

client = TestClient(app)


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


def test_workflow_endpoint_returns_analytics_for_controlled_increase_scenario() -> None:
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
