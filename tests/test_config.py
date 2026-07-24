import os

from pricing_copilot.config import Settings, get_settings


def test_settings_have_sane_defaults():
    settings = Settings()
    assert settings.model_name
    assert settings.policy.max_price_movement_pct == 5.0


def test_settings_read_model_name_from_env(monkeypatch):
    monkeypatch.setenv("PRICING_COPILOT_MODEL_NAME", "test-model")
    get_settings.cache_clear()
    try:
        assert get_settings().model_name == "test-model"
    finally:
        get_settings.cache_clear()
        os.environ.pop("PRICING_COPILOT_MODEL_NAME", None)
