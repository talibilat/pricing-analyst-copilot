from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.generation import (
    DEFAULT_SCENARIO_SEED,
    DEFAULT_SCENARIO_VERSION,
    DRIFT_CURRENT_INDEX,
    DRIFT_TOTAL_MONTHS,
    generate_feedback_topic_series,
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


def test_drift_monitoring_dataset_has_twenty_five_months_with_a_shifted_final_month() -> None:
    dataset = generate_scenario_dataset(ScenarioName.DRIFT_MONITORING)
    assert dataset.scenario is ScenarioName.DRIFT_MONITORING
    assert len(dataset.claims) == DRIFT_TOTAL_MONTHS
    assert len(dataset.conversion) == DRIFT_TOTAL_MONTHS
    assert len(dataset.competitors) == 3 * DRIFT_TOTAL_MONTHS

    baseline_severity = [c.incurred_loss_gbp / c.claim_count for c in dataset.claims[12:24]]
    drift_month = dataset.claims[DRIFT_CURRENT_INDEX]
    drift_severity = drift_month.incurred_loss_gbp / drift_month.claim_count
    average_baseline_severity = sum(baseline_severity) / len(baseline_severity)
    assert drift_severity > average_baseline_severity * 1.2


def test_drift_monitoring_dataset_is_reproducible_from_the_same_seed() -> None:
    first = generate_scenario_dataset(ScenarioName.DRIFT_MONITORING, seed=123, version="v1")
    second = generate_scenario_dataset(ScenarioName.DRIFT_MONITORING, seed=123, version="v1")
    assert first.model_dump() == second.model_dump()


def test_feedback_topic_series_has_a_shifted_final_month() -> None:
    series = generate_feedback_topic_series()
    assert len(series) == DRIFT_TOTAL_MONTHS
    baseline_price_share = [r.price_share_pct for r in series[12:24]]
    average_baseline_price_share = sum(baseline_price_share) / len(baseline_price_share)
    drift_price_share = series[DRIFT_CURRENT_INDEX].price_share_pct
    assert drift_price_share > average_baseline_price_share * 1.5
