from datetime import UTC, datetime
from pathlib import Path

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import DriftReport
from pricing_copilot.drift.store import (
    load_drift_report,
    load_previous_configuration,
    save_drift_report,
    save_previous_configuration,
)


def _versions() -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name="gpt-test",
        recommendation_version="v1",
        governance_version="v1",
        scenario_seed=1,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )


def test_drift_report_round_trips_through_disk(tmp_path: Path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    report = DriftReport(
        report_version="drift-report-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=_versions(),
        alerts=[],
    )
    save_drift_report(report, settings)
    loaded = load_drift_report(settings)
    assert loaded is not None
    assert loaded.report_version == "drift-report-v1"


def test_load_drift_report_returns_none_when_absent(tmp_path: Path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    assert load_drift_report(settings) is None


def test_previous_configuration_round_trips_through_disk(tmp_path: Path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    assert load_previous_configuration(settings) is None
    save_previous_configuration(_versions(), settings)
    loaded = load_previous_configuration(settings)
    assert loaded is not None
    assert loaded.model_name == "gpt-test"
