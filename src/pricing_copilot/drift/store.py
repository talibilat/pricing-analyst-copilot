from __future__ import annotations

from pathlib import Path

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import DriftReport


def _report_path(settings: Settings) -> Path:
    return Path(settings.drift_directory) / "latest.json"


def _previous_configuration_path(settings: Settings) -> Path:
    return Path(settings.drift_directory) / "previous_configuration.json"


def save_drift_report(report: DriftReport, settings: Settings) -> Path:
    path = _report_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    return path


def load_drift_report(settings: Settings) -> DriftReport | None:
    path = _report_path(settings)
    if not path.exists():
        return None
    return DriftReport.model_validate_json(path.read_text())


def load_previous_configuration(settings: Settings) -> ConfigurationVersions | None:
    path = _previous_configuration_path(settings)
    if not path.exists():
        return None
    return ConfigurationVersions.model_validate_json(path.read_text())


def save_previous_configuration(versions: ConfigurationVersions, settings: Settings) -> Path:
    path = _previous_configuration_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(versions.model_dump_json(indent=2))
    return path
