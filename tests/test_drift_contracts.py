from datetime import UTC, datetime

from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import (
    DriftAlert,
    DriftAlertCategory,
    DriftDomain,
    DriftMeasureKind,
    DriftMeasurement,
    DriftReport,
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


def test_drift_report_exposes_only_material_alerts() -> None:
    breached_alert = DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name="claim_severity",
        domain=DriftDomain.CLAIM_SEVERITY,
        measurements=[
            DriftMeasurement(
                measure_kind=DriftMeasureKind.ROLLING_Z_SCORE,
                value=5.0,
                unit="z-score",
                threshold=2.0,
                breached=True,
                comparison_period="month 25 vs months 13-24",
            )
        ],
        breached=True,
        investigation_required=True,
        confidence_impact=0.4,
        baseline_window="months 13-24",
        current_window="month 25",
        detail="Claim severity is 5 baseline standard deviations above normal.",
    )
    quiet_alert = breached_alert.model_copy(
        update={"breached": False, "investigation_required": False, "measurements": []}
    )
    report = DriftReport(
        report_version="drift-report-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=_versions(),
        alerts=[breached_alert, quiet_alert],
    )
    assert report.material_alerts == [breached_alert]
