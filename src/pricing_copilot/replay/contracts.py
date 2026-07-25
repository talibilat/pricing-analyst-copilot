from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from pricing_copilot.chat.contracts import ChatResponse
from pricing_copilot.contracts import ConfigurationVersions, ScenarioName

REPLAY_ARTIFACT_SCHEMA_VERSION = "replay-artifact-schema-v1"


class ReplayArtifact(BaseModel):
    schema_version: str
    scenario: ScenarioName
    recorded_at: datetime
    configuration_versions: ConfigurationVersions
    chat_response: ChatResponse
