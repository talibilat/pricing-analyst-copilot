from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pricing_copilot.chat.contracts import ChatResponse
from pricing_copilot.config import Settings
from pricing_copilot.contracts import ScenarioName
from pricing_copilot.replay.contracts import REPLAY_ARTIFACT_SCHEMA_VERSION, ReplayArtifact
from pricing_copilot.versions import current_configuration_versions


class ReplayArtifactIncompatibleError(ValueError):
    """Raised when a stored replay artifact's schema or configuration versions no longer
    match the running configuration - it must be re-recorded, not silently served."""


class ReplayArtifactMissingError(FileNotFoundError):
    """Raised when no replay artifact has been recorded for a scenario yet."""


def replay_artifact_path(scenario: ScenarioName, settings: Settings) -> Path:
    return Path(settings.replay_directory) / f"{scenario.value}.json"


def save_replay_artifact(response: ChatResponse, settings: Settings) -> ReplayArtifact:
    if response.workflow_result is None:
        raise ValueError("Cannot save a replay artifact for a response with no workflow_result.")
    artifact = ReplayArtifact(
        schema_version=REPLAY_ARTIFACT_SCHEMA_VERSION,
        scenario=response.context.scenario,
        recorded_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(settings),
        chat_response=response,
    )
    path = replay_artifact_path(artifact.scenario, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(indent=2))
    return artifact


def load_replay_artifact(scenario: ScenarioName, settings: Settings) -> ReplayArtifact:
    path = replay_artifact_path(scenario, settings)
    if not path.exists():
        raise ReplayArtifactMissingError(
            f"No replay artifact recorded for scenario {scenario.value!r} at {path}."
        )
    artifact = ReplayArtifact.model_validate_json(path.read_text())

    if artifact.schema_version != REPLAY_ARTIFACT_SCHEMA_VERSION:
        raise ReplayArtifactIncompatibleError(
            f"schema_version: artifact has {artifact.schema_version!r}, current code requires "
            f"{REPLAY_ARTIFACT_SCHEMA_VERSION!r}. Re-record this artifact."
        )
    current = current_configuration_versions(settings)
    if artifact.configuration_versions != current:
        mismatched = [
            field
            for field in type(current).model_fields
            if getattr(artifact.configuration_versions, field) != getattr(current, field)
        ]
        raise ReplayArtifactIncompatibleError(
            f"{', '.join(mismatched)}: artifact configuration versions no longer match the "
            "running configuration. Re-record this artifact."
        )
    return artifact
