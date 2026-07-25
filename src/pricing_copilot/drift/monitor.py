from __future__ import annotations

from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.drift.behavior_detector import detect_behavior_drift
from pricing_copilot.drift.configuration_detector import detect_configuration_drift
from pricing_copilot.drift.contracts import DriftReport
from pricing_copilot.drift.data_detector import detect_data_drift
from pricing_copilot.drift.operational_detector import detect_operational_drift
from pricing_copilot.drift.store import load_previous_configuration, save_previous_configuration
from pricing_copilot.evaluation.contracts import BenchmarkReport
from pricing_copilot.versions import current_configuration_versions

DRIFT_REPORT_VERSION = "drift-report-v1"


def run_drift_monitoring(settings: Settings, benchmark_report: BenchmarkReport) -> DriftReport:
    current_versions = current_configuration_versions(settings)
    previous_versions = load_previous_configuration(settings)

    alerts = [
        *detect_data_drift(settings),
        *detect_behavior_drift(benchmark_report, settings),
        *detect_operational_drift(benchmark_report, settings),
        *detect_configuration_drift(previous_versions, current_versions),
    ]
    save_previous_configuration(current_versions, settings)
    return DriftReport(
        report_version=DRIFT_REPORT_VERSION,
        generated_at=datetime.now(UTC),
        configuration_versions=current_versions,
        alerts=alerts,
    )
