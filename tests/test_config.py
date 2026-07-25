import os

import pytest

from pricing_copilot.config import PolicySettings, Settings, get_settings


def test_settings_have_sane_defaults() -> None:
    settings = Settings()
    assert settings.model_name
    assert settings.policy.max_price_movement_pct == 5.0
    assert settings.policy.minimum_source_types >= 3
    assert settings.policy.require_human_approval is True
    assert settings.max_retries == 1


def test_mandatory_policy_controls_cannot_be_disabled() -> None:
    with pytest.raises(ValueError, match="mandatory controls"):
        PolicySettings(require_human_approval=False)


def test_price_movement_policy_cannot_exceed_five_percent() -> None:
    with pytest.raises(ValueError):
        PolicySettings(max_price_movement_pct=5.1)


def test_automatic_retries_cannot_exceed_one() -> None:
    with pytest.raises(ValueError):
        Settings(max_retries=2)


def test_settings_read_model_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICING_COPILOT_MODEL_NAME", "test-model")
    get_settings.cache_clear()
    try:
        assert get_settings().model_name == "test-model"
    finally:
        get_settings.cache_clear()
        os.environ.pop("PRICING_COPILOT_MODEL_NAME", None)
