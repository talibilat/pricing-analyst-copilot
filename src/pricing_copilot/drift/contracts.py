from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from pricing_copilot.contracts import ConfigurationVersions


class DriftDomain(StrEnum):
    CLAIM_SEVERITY = "claim_severity"
    CLAIM_FREQUENCY = "claim_frequency"
    LOSS_RATIO = "loss_ratio"
    CONVERSION = "conversion"
    COMPETITOR_INDEX = "competitor_index"
    FEEDBACK_TOPICS = "feedback_topics"


class DriftMeasureKind(StrEnum):
    POPULATION_STABILITY_INDEX = "population_stability_index"
    KOLMOGOROV_SMIRNOV = "kolmogorov_smirnov"
    PERCENTAGE_MOVEMENT = "percentage_movement"
    ROLLING_Z_SCORE = "rolling_z_score"


class DriftAlertCategory(StrEnum):
    DATA = "data"
    BEHAVIOR = "behavior"
    OPERATIONAL = "operational"
    CONFIGURATION = "configuration"


class DriftMeasurement(BaseModel):
    measure_kind: DriftMeasureKind
    value: float
    unit: str
    threshold: float
    breached: bool
    comparison_period: str


class DriftAlert(BaseModel):
    category: DriftAlertCategory
    metric_name: str
    domain: DriftDomain | None = None
    measurements: list[DriftMeasurement] = Field(default_factory=list)
    breached: bool
    investigation_required: bool
    confidence_impact: float = 0.0
    insufficient_sample: bool = False
    baseline_window: str
    current_window: str
    detail: str


class DriftReport(BaseModel):
    report_version: str
    generated_at: datetime
    configuration_versions: ConfigurationVersions
    alerts: list[DriftAlert] = Field(default_factory=list)

    @property
    def material_alerts(self) -> list[DriftAlert]:
        return [alert for alert in self.alerts if alert.breached and alert.investigation_required]
