from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PolicySettings(BaseModel):
    max_price_movement_pct: float = Field(default=5.0, gt=0.0, le=5.0)
    max_evidence_age_days: int = Field(default=120, gt=0)
    minimum_source_types: int = Field(default=3, ge=3)
    require_claims_evidence: bool = True
    require_conversion_evidence: bool = True
    require_human_approval: bool = True
    prohibit_customer_level_actions: bool = True
    prohibited_attributes: tuple[str, ...] = (
        "age",
        "disability",
        "ethnicity",
        "gender reassignment",
        "marital status",
        "pregnancy",
        "race",
        "religion",
        "sex",
        "sexual orientation",
    )

    @model_validator(mode="after")
    def prevent_policy_weakening(self) -> PolicySettings:
        required_flags = (
            self.require_claims_evidence,
            self.require_conversion_evidence,
            self.require_human_approval,
            self.prohibit_customer_level_actions,
        )
        if not all(required_flags):
            raise ValueError(
                "Claims evidence, conversion evidence, human approval, and the customer-level "
                "action prohibition are mandatory controls."
            )
        if not self.prohibited_attributes:
            raise ValueError("At least one protected attribute must remain prohibited.")
        return self


class CostSettings(BaseModel):
    input_cost_per_million_tokens_gbp: float = Field(default=0.0, ge=0.0)
    output_cost_per_million_tokens_gbp: float = Field(default=0.0, ge=0.0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRICING_COPILOT_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    model_name: str = "gpt-4.1-mini"
    request_timeout_seconds: float = Field(default=30.0, gt=0.0)
    max_workflow_seconds: float = Field(default=90.0, gt=0.0)
    tool_timeout_seconds: float = Field(default=5.0, gt=0.0)
    max_agent_turns: int = Field(default=6, ge=1)
    max_tool_calls_per_agent: int = Field(default=4, ge=1)
    max_retries: int = Field(default=1, ge=0, le=1)
    local_tracing_enabled: bool = True
    agents_sdk_tracing_enabled: bool = True
    trace_directory: Path = Path("var/traces")
    policy: PolicySettings = PolicySettings()
    cost: CostSettings = CostSettings()
    decision_store_path: str = "var/decisions.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()


class AzureOpenAISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AZURE_OPENAI_", env_file=".env", extra="ignore")

    api_key: str | None = None
    endpoint: str | None = None
    chat_deployment: str | None = None


@lru_cache
def get_azure_openai_settings() -> AzureOpenAISettings:
    return AzureOpenAISettings()
