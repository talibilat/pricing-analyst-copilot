import math

import pytest

from pricing_copilot.drift.statistics import (
    kolmogorov_smirnov,
    percentage_movement,
    population_stability_index,
    rolling_z_score,
)


def test_population_stability_index_is_zero_for_identical_distributions() -> None:
    assert population_stability_index([0.5, 0.5], [0.5, 0.5]) == pytest.approx(0.0, abs=1e-9)


def test_population_stability_index_is_large_for_a_big_shift() -> None:
    assert population_stability_index([0.9, 0.1], [0.5, 0.5]) > 0.2


def test_kolmogorov_smirnov_reports_no_difference_for_identical_samples() -> None:
    sample = [float(x) for x in range(50)]
    statistic, p_value = kolmogorov_smirnov(sample, sample)
    assert statistic == pytest.approx(0.0)
    assert p_value == pytest.approx(1.0)


def test_kolmogorov_smirnov_detects_a_shifted_sample() -> None:
    baseline = [float(x) for x in range(50)]
    shifted = [float(x) + 100 for x in range(50)]
    statistic, p_value = kolmogorov_smirnov(baseline, shifted)
    assert statistic == pytest.approx(1.0)
    assert p_value < 0.01


def test_percentage_movement_computes_signed_percentage() -> None:
    assert percentage_movement(100.0, 125.0) == pytest.approx(25.0)
    assert percentage_movement(100.0, 75.0) == pytest.approx(-25.0)


def test_percentage_movement_handles_zero_baseline() -> None:
    assert percentage_movement(0.0, 0.0) == 0.0
    assert percentage_movement(0.0, 5.0) == math.inf


def test_rolling_z_score_is_zero_at_the_baseline_mean() -> None:
    assert rolling_z_score([8.0, 9.0, 10.0, 11.0, 12.0], 10.0) == pytest.approx(0.0)


def test_rolling_z_score_is_large_for_an_outlier() -> None:
    baseline = [10.0, 10.1, 9.9, 10.0, 10.05, 9.95]
    assert abs(rolling_z_score(baseline, 20.0)) > 3.0


def test_rolling_z_score_handles_zero_variance_baseline() -> None:
    assert rolling_z_score([10.0, 10.0, 10.0], 10.0) == 0.0
    assert rolling_z_score([10.0, 10.0, 10.0], 15.0) == math.inf


def test_rolling_z_score_requires_at_least_two_baseline_points() -> None:
    with pytest.raises(ValueError, match="at least two"):
        rolling_z_score([10.0], 10.0)
