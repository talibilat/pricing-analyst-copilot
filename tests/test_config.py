import os

import pytest

from pricing_copilot.config import (
    PolicySettings,
    Settings,
    azure_openai_base_url,
    get_settings,
)


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


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (
            "https://example.cognitiveservices.azure.com",
            "https://example.cognitiveservices.azure.com/openai/v1",
        ),
        (
            "https://example.cognitiveservices.azure.com/openai/v1",
            "https://example.cognitiveservices.azure.com/openai/v1",
        ),
        (
            "https://example.cognitiveservices.azure.com/openai/responses",
            "https://example.cognitiveservices.azure.com/openai/v1",
        ),
        (
            "https://example.openai.azure.com/openai/deployments/example/chat/completions"
            "?api-version=2025-01-01-preview",
            "https://example.openai.azure.com/openai/v1",
        ),
    ],
)
def test_azure_openai_base_url_normalizes_resource_and_api_endpoints(
    endpoint: str,
    expected: str,
) -> None:
    assert azure_openai_base_url(endpoint) == expected
