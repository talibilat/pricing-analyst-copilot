from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.generation import (
    DEFAULT_SCENARIO_SEED,
    DEFAULT_SCENARIO_VERSION,
    generate_scenario_dataset,
)


def test_dataset_has_24_monthly_periods_per_domain() -> None:
    dataset = generate_scenario_dataset(ScenarioName.CONTROLLED_INCREASE)
    assert len({r.period for r in dataset.claims}) == 24
    assert len({r.period for r in dataset.competitors}) == 24
    renewal_conversion = [r for r in dataset.conversion if r.segment.value == "renewal"]
    assert len({r.period for r in renewal_conversion}) == 24


def test_generation_is_byte_for_byte_reproducible_for_same_seed() -> None:
    first = generate_scenario_dataset(ScenarioName.CONTROLLED_INCREASE, seed=42, version="v1")
    second = generate_scenario_dataset(ScenarioName.CONTROLLED_INCREASE, seed=42, version="v1")
    assert first.model_dump_json() == second.model_dump_json()


def test_generation_differs_for_a_different_seed() -> None:
    first = generate_scenario_dataset(ScenarioName.CONTROLLED_INCREASE, seed=1, version="v1")
    second = generate_scenario_dataset(ScenarioName.CONTROLLED_INCREASE, seed=2, version="v1")
    assert first.model_dump_json() != second.model_dump_json()


def test_default_seed_and_version_are_stable_constants() -> None:
    assert isinstance(DEFAULT_SCENARIO_SEED, int)
    assert isinstance(DEFAULT_SCENARIO_VERSION, str)


def test_retention_concern_dataset_has_24_monthly_periods_per_domain() -> None:
    dataset = generate_scenario_dataset(ScenarioName.RETENTION_CONCERN)
    assert len({r.period for r in dataset.claims}) == 24
    assert len({r.period for r in dataset.competitors}) == 24


def test_conflicting_evidence_dataset_has_incomplete_conversion_data() -> None:
    dataset = generate_scenario_dataset(ScenarioName.CONFLICTING_EVIDENCE)
    renewal_conversion = [r for r in dataset.conversion if r.segment.value == "renewal"]
    assert len({r.period for r in renewal_conversion}) < 24
    assert len({r.period for r in dataset.claims}) == 24


def test_all_three_scenarios_are_byte_for_byte_reproducible() -> None:
    for scenario in ScenarioName:
        first = generate_scenario_dataset(scenario, seed=7, version="v1")
        second = generate_scenario_dataset(scenario, seed=7, version="v1")
        assert first.model_dump_json() == second.model_dump_json()
