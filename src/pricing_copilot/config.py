from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PolicySettings(BaseModel):
    max_price_movement_pct: float = 5.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRICING_COPILOT_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    model_name: str = "gpt-4.1-mini"
    request_timeout_seconds: float = 30.0
    max_agent_turns: int = 6
    policy: PolicySettings = PolicySettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
