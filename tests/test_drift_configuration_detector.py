from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.configuration_detector import detect_configuration_drift


def _versions(**overrides: object) -> ConfigurationVersions:
    base = ConfigurationVersions(
        model_name="gpt-test",
        recommendation_version="v1",
        governance_version="v1",
        scenario_seed=1,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )
    return base.model_copy(update=overrides)


def test_detect_configuration_drift_flags_no_previous_snapshot_as_insufficient_sample() -> None:
    alerts = detect_configuration_drift(None, _versions())
    assert len(alerts) == 1
    assert alerts[0].insufficient_sample is True
    assert alerts[0].breached is False


def test_detect_configuration_drift_reports_no_change_when_identical() -> None:
    versions = _versions()
    alerts = detect_configuration_drift(versions, versions)
    assert len(alerts) == 1
    assert alerts[0].breached is False


def test_detect_configuration_drift_flags_every_changed_field() -> None:
    previous = _versions(model_name="gpt-old")
    current = _versions(model_name="gpt-new")
    alerts = detect_configuration_drift(previous, current)
    changed = next(a for a in alerts if a.metric_name == "model_name")
    assert changed.breached is True
    assert changed.investigation_required is True
    assert "gpt-old" in changed.detail
    assert "gpt-new" in changed.detail
