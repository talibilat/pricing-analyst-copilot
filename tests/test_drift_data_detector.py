from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlertCategory, DriftDomain
from pricing_copilot.drift.data_detector import detect_data_drift


def test_detect_data_drift_returns_one_alert_per_domain(tmp_path) -> None:
    settings = Settings(analytics_database_path=tmp_path / "test.duckdb")
    alerts = detect_data_drift(settings)
    domains = {alert.domain for alert in alerts}
    assert domains == set(DriftDomain)
    assert all(alert.category is DriftAlertCategory.DATA for alert in alerts)


def test_detect_data_drift_flags_claim_severity_as_breached() -> None:
    settings = Settings(analytics_database_path=Settings().analytics_database_path)
    alerts = detect_data_drift(settings)
    severity_alert = next(a for a in alerts if a.domain is DriftDomain.CLAIM_SEVERITY)
    assert severity_alert.breached is True
    assert severity_alert.investigation_required is True
    assert severity_alert.measurements


def test_detect_data_drift_flags_feedback_topics_via_psi() -> None:
    settings = Settings(analytics_database_path=Settings().analytics_database_path)
    alerts = detect_data_drift(settings)
    feedback_alert = next(a for a in alerts if a.domain is DriftDomain.FEEDBACK_TOPICS)
    assert feedback_alert.breached is True
    kinds = {m.measure_kind.value for m in feedback_alert.measurements}
    assert "population_stability_index" in kinds
