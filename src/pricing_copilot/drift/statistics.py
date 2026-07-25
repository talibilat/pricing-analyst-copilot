from __future__ import annotations

import math
import statistics

from scipy import stats

_EPSILON = 1e-6


def population_stability_index(
    baseline_proportions: list[float], current_proportions: list[float]
) -> float:
    """Compare pre-defined bucket/category proportions between two distributions."""
    if len(baseline_proportions) != len(current_proportions):
        raise ValueError("baseline and current proportions must have the same number of buckets")
    total = 0.0
    for baseline, current in zip(baseline_proportions, current_proportions, strict=True):
        safe_baseline = max(baseline, _EPSILON)
        safe_current = max(current, _EPSILON)
        total += (safe_current - safe_baseline) * math.log(safe_current / safe_baseline)
    return total


def kolmogorov_smirnov(baseline: list[float], current: list[float]) -> tuple[float, float]:
    """Two-sample KS test; returns (statistic, p_value). A low p_value indicates drift."""
    result = stats.ks_2samp(baseline, current)
    return float(result.statistic), float(result.pvalue)


def percentage_movement(baseline_mean: float, current_value: float) -> float:
    if baseline_mean == 0:
        return 0.0 if current_value == 0 else math.inf
    return ((current_value - baseline_mean) / baseline_mean) * 100.0


def rolling_z_score(baseline: list[float], current_value: float) -> float:
    if len(baseline) < 2:
        raise ValueError("rolling_z_score requires at least two baseline observations")
    mean = statistics.mean(baseline)
    stdev = statistics.stdev(baseline)
    if stdev == 0:
        return 0.0 if current_value == mean else math.inf
    return (current_value - mean) / stdev
