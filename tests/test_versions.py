from pricing_copilot.config import get_settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.versions import GOVERNED_RECOMMENDATION_VERSION, current_configuration_versions


def test_current_configuration_versions_returns_a_fully_populated_object() -> None:
    versions = current_configuration_versions(get_settings())
    assert isinstance(versions, ConfigurationVersions)
    assert versions.recommendation_version == GOVERNED_RECOMMENDATION_VERSION
    assert versions.output_schema_version


def test_current_configuration_versions_is_deterministic_for_the_same_settings() -> None:
    settings = get_settings()
    assert current_configuration_versions(settings) == current_configuration_versions(settings)
