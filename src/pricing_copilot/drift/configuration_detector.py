from __future__ import annotations

from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory

BASELINE_WINDOW_LABEL = "previously recorded configuration"
CURRENT_WINDOW_LABEL = "current configuration"


def detect_configuration_drift(
    previous: ConfigurationVersions | None, current: ConfigurationVersions
) -> list[DriftAlert]:
    if previous is None:
        return [
            DriftAlert(
                category=DriftAlertCategory.CONFIGURATION,
                metric_name="configuration_baseline",
                breached=False,
                investigation_required=False,
                insufficient_sample=True,
                baseline_window=BASELINE_WINDOW_LABEL,
                current_window=CURRENT_WINDOW_LABEL,
                detail=(
                    "No previous configuration snapshot exists yet; "
                    "this run establishes the baseline."
                ),
            )
        ]

    previous_fields = previous.model_dump()
    current_fields = current.model_dump()
    changed = {
        field: (previous_fields[field], current_fields[field])
        for field in current_fields
        if previous_fields.get(field) != current_fields[field]
    }
    if not changed:
        return [
            DriftAlert(
                category=DriftAlertCategory.CONFIGURATION,
                metric_name="configuration_versions",
                breached=False,
                investigation_required=False,
                baseline_window=BASELINE_WINDOW_LABEL,
                current_window=CURRENT_WINDOW_LABEL,
                detail="No configuration fields changed since the previous snapshot.",
            )
        ]

    return [
        DriftAlert(
            category=DriftAlertCategory.CONFIGURATION,
            metric_name=field,
            breached=True,
            investigation_required=True,
            confidence_impact=0.1,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"{field} changed from {old_value!r} to {new_value!r}.",
        )
        for field, (old_value, new_value) in changed.items()
    ]
