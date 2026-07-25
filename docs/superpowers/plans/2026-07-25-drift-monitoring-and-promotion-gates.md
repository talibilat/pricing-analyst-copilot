# Drift Monitoring and Evaluated Change-Promotion Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a drift-monitoring journey (data, agent-behavior, operational, and configuration drift) built on a reproducible 25-month dataset, plus an evaluated change-promotion gate that blocks a configuration from becoming the default unless the golden evaluation suite passes.

**Architecture:** A new `drift/` package holds typed contracts, pure statistics functions (PSI, KS-test, percentage movement, rolling z-score), and four detectors (data, behavior, operational, configuration) that assemble a `DriftReport`. Data drift reads a new `ScenarioName.DRIFT_MONITORING` dataset (24 stable months + 1 deliberately-shifted 25th month) through the existing `PersistentAnalyticsDatabase`. Behavior and operational drift read the existing golden-evaluation `BenchmarkReport`. Configuration drift diffs two persisted `ConfigurationVersions` snapshots. A new `evaluation/gate.py` compares a `BenchmarkReport`'s actuals against its targets to decide whether a report may be "promoted" as the current default, mirroring the existing `evaluation/store.py` persistence pattern. The chat `DRIFT` intent (currently a stub) and a new Streamlit "Monitoring" tab both render the persisted `DriftReport`.

**Tech Stack:** Python 3.12, Pydantic v2, DuckDB (via the existing `PersistentAnalyticsDatabase`), scipy (new dependency, for the Kolmogorov-Smirnov test), pytest, Streamlit.

## Global Constraints

- Data drift monitoring must cover exactly these six domains: claim severity, claim frequency, loss ratio, conversion, competitor index, aggregate feedback topics.
- Explainable drift measures: population stability index, Kolmogorov-Smirnov test, percentage movement, rolling z-score - applied where statistically appropriate to each domain (not all four to every domain).
- Agent-behavior monitoring must cover: routing accuracy, citation coverage, safe abstention, recommendation distribution, governance rejection, golden-suite pass rate.
- Operational monitoring must cover: latency, token use, estimated cost, tool failures, retries, invalid structured outputs.
- Configuration monitoring must record: model, prompt, agent, tool, dataset, and policy versions.
- The month-25 dataset must be versioned and reproduce the same drift signals deterministically (fixed seed).
- Thresholds must be configurable (via `Settings`) and every measurement must display its unit and comparison period.
- Baseline windows and insufficient-sample behavior must be explicit and testable.
- A change cannot be promoted as the default unless all required evaluation gates pass; a failed promotion must record the failing cases/metrics and leave the current default untouched.
- The drift demonstration must work without live Azure credentials (pure computation over already-persisted data).
- Never use an em dash in any file this plan creates or edits - use a plain hyphen instead.
- Follow the existing TDD/quality-suite/commit cadence used throughout this repository: failing test -> verify red -> implement -> verify green -> commit, then `./scripts/quality.sh` before closing out.

---

### Task 1: Month-25 drift dataset and feedback-topic series

**Files:**
- Modify: `src/pricing_copilot/contracts.py` (add `ScenarioName.DRIFT_MONITORING`)
- Modify: `src/pricing_copilot/data/records.py` (add `FeedbackTopicMonthlyRecord`)
- Modify: `src/pricing_copilot/data/generation.py` (add the drift dataset generator and feedback-topic series generator)
- Test: `tests/test_data_generation.py`

**Interfaces:**
- Consumes: existing `_month_periods`, `_jitter`, `COMPETITOR_BASE_INDEX`, `Product`/`Region`/`Segment` enums, `ScenarioDataset`.
- Produces: `ScenarioName.DRIFT_MONITORING` member; `DRIFT_TOTAL_MONTHS = 25`; `DRIFT_CURRENT_INDEX = 24`; `generate_scenario_dataset(ScenarioName.DRIFT_MONITORING, ...) -> ScenarioDataset` (25 months of claims/conversion/competitors/pricing_history, months 0-23 stable, month 24 deliberately shifted); `generate_feedback_topic_series(seed: int = DEFAULT_SCENARIO_SEED, *, months: int = DRIFT_TOTAL_MONTHS) -> list[FeedbackTopicMonthlyRecord]` (a standalone series, NOT part of `ScenarioDataset` - it is not stored in DuckDB, later tasks read it directly).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_generation.py (add to the existing file)
from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.generation import (
    DRIFT_CURRENT_INDEX,
    DRIFT_TOTAL_MONTHS,
    generate_feedback_topic_series,
    generate_scenario_dataset,
)


def test_drift_monitoring_dataset_has_twenty_five_months_with_a_shifted_final_month() -> None:
    dataset = generate_scenario_dataset(ScenarioName.DRIFT_MONITORING)
    assert dataset.scenario is ScenarioName.DRIFT_MONITORING
    assert len(dataset.claims) == DRIFT_TOTAL_MONTHS
    assert len(dataset.conversion) == DRIFT_TOTAL_MONTHS
    assert len(dataset.competitors) == 3 * DRIFT_TOTAL_MONTHS

    baseline_severity = [
        c.incurred_loss_gbp / c.claim_count
        for c in dataset.claims[12:24]
    ]
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_data_generation.py -k drift_monitoring -v`
Expected: FAIL - `ScenarioName.DRIFT_MONITORING` / `DRIFT_TOTAL_MONTHS` do not exist yet.

- [ ] **Step 3: Implement**

In `src/pricing_copilot/contracts.py`, extend the enum:

```python
class ScenarioName(StrEnum):
    CONTROLLED_INCREASE = "controlled_increase"
    RETENTION_CONCERN = "retention_concern"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    DRIFT_MONITORING = "drift_monitoring"
```

In `src/pricing_copilot/data/records.py`, add:

```python
class FeedbackTopicMonthlyRecord(BaseModel):
    period: date
    claims_handling_share_pct: float
    price_share_pct: float
    communication_share_pct: float
    other_share_pct: float
```

In `src/pricing_copilot/data/generation.py`, add near the top (after `TOTAL_MONTHS`/`SCENARIO_START_MONTH`):

```python
DRIFT_TOTAL_MONTHS = 25
DRIFT_CURRENT_INDEX = 24  # the 25th month, deliberately shifted to trigger drift signals
```

Add `FeedbackTopicMonthlyRecord` to the `from pricing_copilot.data.records import (...)` block, then append these functions before `generate_scenario_dataset`:

```python
def _generate_drift_monitoring_claims(
    rng: random.Random, periods: list[date]
) -> list[ClaimsMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_drift_month = index == DRIFT_CURRENT_INDEX
        policies = round(_jitter(rng, 5000, 0.01))
        claim_count = round(_jitter(rng, 420, 0.03) * (1.35 if is_drift_month else 1.0))
        severity_target = 1606.0 * (1.45 if is_drift_month else 1.0)
        severity = _jitter(rng, severity_target, 0.02)
        earned_premium = round(_jitter(rng, 950_000.0, 0.01), 2)
        records.append(
            ClaimsMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                policies_in_force=policies,
                claim_count=claim_count,
                incurred_loss_gbp=round(claim_count * severity, 2),
                earned_premium_gbp=earned_premium,
            )
        )
    return records


def _generate_drift_monitoring_conversion(
    rng: random.Random, periods: list[date]
) -> list[ConversionMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_drift_month = index == DRIFT_CURRENT_INDEX
        conv_target = 0.22 * (0.70 if is_drift_month else 1.0)
        ret_target = 0.88 * (0.85 if is_drift_month else 1.0)
        quotes = round(_jitter(rng, 10_000, 0.02))
        sales = round(quotes * _jitter(rng, conv_target, 0.03))
        renewals_due = round(_jitter(rng, 4_000, 0.02))
        renewals_retained = round(renewals_due * _jitter(rng, ret_target, 0.02))
        premium = round(_jitter(rng, 620.0, 0.01), 2)
        records.append(
            ConversionMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                quotes=quotes,
                sales=sales,
                renewals_due=renewals_due,
                renewals_retained=renewals_retained,
                average_quoted_premium_gbp=premium,
            )
        )
    return records


def _generate_drift_monitoring_competitors(
    rng: random.Random, periods: list[date]
) -> list[CompetitorMonthlyRecord]:
    records = []
    for name, base_index in COMPETITOR_BASE_INDEX.items():
        for index, period in enumerate(periods):
            is_drift_month = index == DRIFT_CURRENT_INDEX
            target = base_index * (1.20 if is_drift_month else 1.0)
            records.append(
                CompetitorMonthlyRecord(
                    period=period,
                    region=Region.NORTH_WEST,
                    competitor_name=name,
                    price_index=round(_jitter(rng, target, 0.01), 2),
                )
            )
    return records


def _generate_drift_monitoring_dataset(seed: int, version: str) -> ScenarioDataset:
    rng = random.Random(seed)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, DRIFT_TOTAL_MONTHS)
    return ScenarioDataset(
        scenario=ScenarioName.DRIFT_MONITORING,
        seed=seed,
        version=version,
        claims=_generate_drift_monitoring_claims(rng, periods),
        conversion=_generate_drift_monitoring_conversion(rng, periods),
        competitors=_generate_drift_monitoring_competitors(rng, periods),
        pricing_history=_generate_pricing_history(periods),
    )


def generate_feedback_topic_series(
    seed: int = DEFAULT_SCENARIO_SEED, *, months: int = DRIFT_TOTAL_MONTHS
) -> list[FeedbackTopicMonthlyRecord]:
    """A standalone monthly topic-share series for feedback-topic drift detection.

    Not part of ScenarioDataset/the persistent DuckDB store - this is purpose-built,
    lightweight time series data consumed directly by the drift data detector.
    """
    rng = random.Random(seed + 1)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, months)
    records = []
    for index, period in enumerate(periods):
        is_drift_month = index == DRIFT_CURRENT_INDEX
        if is_drift_month:
            claims_share, price_share, comms_share = 0.30, 0.45, 0.15
        else:
            claims_share, price_share, comms_share = 0.55, 0.15, 0.20
        other_share = max(0.0, 1.0 - claims_share - price_share - comms_share)
        records.append(
            FeedbackTopicMonthlyRecord(
                period=period,
                claims_handling_share_pct=round(claims_share * 100, 2),
                price_share_pct=round(price_share * 100, 2),
                communication_share_pct=round(comms_share * 100, 2),
                other_share_pct=round(other_share * 100, 2),
            )
        )
    return records
```

Update the dispatcher:

```python
def generate_scenario_dataset(
    scenario: ScenarioName,
    seed: int = DEFAULT_SCENARIO_SEED,
    version: str = DEFAULT_SCENARIO_VERSION,
) -> ScenarioDataset:
    if scenario is ScenarioName.CONTROLLED_INCREASE:
        return _generate_controlled_increase_dataset(seed, version)
    if scenario is ScenarioName.RETENTION_CONCERN:
        return _generate_retention_concern_dataset(seed, version)
    if scenario is ScenarioName.CONFLICTING_EVIDENCE:
        return _generate_conflicting_evidence_dataset(seed, version)
    if scenario is ScenarioName.DRIFT_MONITORING:
        return _generate_drift_monitoring_dataset(seed, version)
    raise NotImplementedError(f"No generator implemented yet for scenario '{scenario.value}'.")
```

Note: `ScenarioName.DRIFT_MONITORING` must NOT be added to `IMPLEMENTED_DATA_SCENARIOS` in `src/pricing_copilot/workflow_common.py` - it is a monitoring-only dataset, not a priceable scenario. `build_analytics_database()` in `src/pricing_copilot/data/persistent.py` iterates `ScenarioName` automatically and needs no code change to pick up the new member.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_data_generation.py -v`
Expected: PASS (all tests, including the new ones).

- [ ] **Step 5: Verify the persistent DuckDB build picks up the new scenario automatically**

```python
# tests/test_persistent_data.py (add to the existing file)
from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.persistent import build_analytics_database


def test_build_analytics_database_includes_the_drift_monitoring_scenario(tmp_path):
    path = build_analytics_database(tmp_path / "test.duckdb")
    import duckdb

    connection = duckdb.connect(str(path), read_only=True)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM claims WHERE scenario = ?", [ScenarioName.DRIFT_MONITORING.value]
        ).fetchone()
    finally:
        connection.close()
    assert count is not None and count[0] == 25
```

Run: `uv run pytest tests/test_persistent_data.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pricing_copilot/contracts.py src/pricing_copilot/data/records.py src/pricing_copilot/data/generation.py tests/test_data_generation.py tests/test_persistent_data.py
git commit -m "feat: add the reproducible month-25 drift monitoring dataset"
```

---

### Task 2: Drift statistics functions (PSI, KS-test, percentage movement, rolling z-score)

**Files:**
- Modify: `pyproject.toml` (add `scipy` dependency and a mypy override)
- Create: `src/pricing_copilot/drift/__init__.py`
- Create: `src/pricing_copilot/drift/statistics.py`
- Test: `tests/test_drift_statistics.py`

**Interfaces:**
- Produces: `population_stability_index(baseline_proportions: list[float], current_proportions: list[float]) -> float`; `kolmogorov_smirnov(baseline: list[float], current: list[float]) -> tuple[float, float]` (statistic, p_value); `percentage_movement(baseline_mean: float, current_value: float) -> float`; `rolling_z_score(baseline: list[float], current_value: float) -> float`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"scipy>=1.13",` to `dependencies`, and add a mypy override block:

```toml
[[tool.mypy.overrides]]
module = "scipy.*"
ignore_missing_imports = true
```

Run: `uv sync --all-groups`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_drift_statistics.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_drift_statistics.py -v`
Expected: FAIL with "No module named 'pricing_copilot.drift'".

- [ ] **Step 4: Implement**

Create `src/pricing_copilot/drift/__init__.py` (empty).

Create `src/pricing_copilot/drift/statistics.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_drift_statistics.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/pricing_copilot/drift/__init__.py src/pricing_copilot/drift/statistics.py tests/test_drift_statistics.py
git commit -m "feat: add PSI, KS-test, percentage movement, and rolling z-score statistics"
```

---

### Task 3: Drift contracts and configurable thresholds

**Files:**
- Modify: `src/pricing_copilot/config.py` (add `DriftPolicySettings` and `drift_directory`)
- Create: `src/pricing_copilot/drift/contracts.py`
- Test: `tests/test_drift_contracts.py`

**Interfaces:**
- Consumes: `pricing_copilot.contracts.ConfigurationVersions`.
- Produces: `DriftDomain`, `DriftMeasureKind`, `DriftAlertCategory` (StrEnums); `DriftMeasurement`, `DriftAlert`, `DriftReport` (Pydantic models); `Settings.drift: DriftPolicySettings`; `Settings.drift_directory: Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift_contracts.py
from datetime import UTC, datetime

from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import (
    DriftAlert,
    DriftAlertCategory,
    DriftDomain,
    DriftMeasureKind,
    DriftMeasurement,
    DriftReport,
)


def _versions() -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name="gpt-test",
        recommendation_version="v1",
        governance_version="v1",
        scenario_seed=1,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )


def test_drift_report_exposes_only_material_alerts() -> None:
    breached_alert = DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name="claim_severity",
        domain=DriftDomain.CLAIM_SEVERITY,
        measurements=[
            DriftMeasurement(
                measure_kind=DriftMeasureKind.ROLLING_Z_SCORE,
                value=5.0,
                unit="z-score",
                threshold=2.0,
                breached=True,
                comparison_period="month 25 vs months 13-24",
            )
        ],
        breached=True,
        investigation_required=True,
        confidence_impact=0.4,
        baseline_window="months 13-24",
        current_window="month 25",
        detail="Claim severity is 5 baseline standard deviations above normal.",
    )
    quiet_alert = breached_alert.model_copy(
        update={"breached": False, "investigation_required": False, "measurements": []}
    )
    report = DriftReport(
        report_version="drift-report-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=_versions(),
        alerts=[breached_alert, quiet_alert],
    )
    assert report.material_alerts == [breached_alert]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_drift_contracts.py -v`
Expected: FAIL - `pricing_copilot.drift.contracts` does not exist.

- [ ] **Step 3: Implement**

Create `src/pricing_copilot/drift/contracts.py`:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from pricing_copilot.contracts import ConfigurationVersions


class DriftDomain(StrEnum):
    CLAIM_SEVERITY = "claim_severity"
    CLAIM_FREQUENCY = "claim_frequency"
    LOSS_RATIO = "loss_ratio"
    CONVERSION = "conversion"
    COMPETITOR_INDEX = "competitor_index"
    FEEDBACK_TOPICS = "feedback_topics"


class DriftMeasureKind(StrEnum):
    POPULATION_STABILITY_INDEX = "population_stability_index"
    KOLMOGOROV_SMIRNOV = "kolmogorov_smirnov"
    PERCENTAGE_MOVEMENT = "percentage_movement"
    ROLLING_Z_SCORE = "rolling_z_score"


class DriftAlertCategory(StrEnum):
    DATA = "data"
    BEHAVIOR = "behavior"
    OPERATIONAL = "operational"
    CONFIGURATION = "configuration"


class DriftMeasurement(BaseModel):
    measure_kind: DriftMeasureKind
    value: float
    unit: str
    threshold: float
    breached: bool
    comparison_period: str


class DriftAlert(BaseModel):
    category: DriftAlertCategory
    metric_name: str
    domain: DriftDomain | None = None
    measurements: list[DriftMeasurement] = Field(default_factory=list)
    breached: bool
    investigation_required: bool
    confidence_impact: float = 0.0
    insufficient_sample: bool = False
    baseline_window: str
    current_window: str
    detail: str


class DriftReport(BaseModel):
    report_version: str
    generated_at: datetime
    configuration_versions: ConfigurationVersions
    alerts: list[DriftAlert] = Field(default_factory=list)

    @property
    def material_alerts(self) -> list[DriftAlert]:
        return [alert for alert in self.alerts if alert.breached and alert.investigation_required]
```

In `src/pricing_copilot/config.py`, add after `CostSettings`:

```python
class DriftPolicySettings(BaseModel):
    psi_threshold: float = Field(default=0.2, gt=0.0)
    ks_p_value_threshold: float = Field(default=0.05, gt=0.0, lt=1.0)
    percentage_movement_threshold_pct: float = Field(default=20.0, gt=0.0)
    z_score_threshold: float = Field(default=2.0, gt=0.0)
    minimum_baseline_months: int = Field(default=6, ge=1)
    routing_accuracy_floor_pct: float = Field(default=90.0, ge=0.0, le=100.0)
    citation_coverage_floor_pct: float = Field(default=95.0, ge=0.0, le=100.0)
    safe_abstention_floor_pct: float = Field(default=95.0, ge=0.0, le=100.0)
    governance_rejection_ceiling_count: int = Field(default=0, ge=0)
    golden_suite_pass_floor_pct: float = Field(default=100.0, ge=0.0, le=100.0)
    latency_p95_ceiling_seconds: float = Field(default=30.0, gt=0.0)
    tool_failure_ceiling_pct: float = Field(default=5.0, ge=0.0, le=100.0)
```

Add to `Settings`:

```python
    drift_directory: Path = Path("var/drift")
    drift: DriftPolicySettings = DriftPolicySettings()
```

(Insert `drift_directory` next to `evaluation_directory`, and `drift: DriftPolicySettings = DriftPolicySettings()` next to `policy: PolicySettings = PolicySettings()`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_drift_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/drift/contracts.py src/pricing_copilot/config.py tests/test_drift_contracts.py
git commit -m "feat: add drift report contracts and configurable drift policy thresholds"
```

---

### Task 4: Data drift detector

**Files:**
- Create: `src/pricing_copilot/drift/data_detector.py`
- Test: `tests/test_drift_data_detector.py`

**Interfaces:**
- Consumes: `pricing_copilot.data.persistent.PersistentAnalyticsDatabase`, `pricing_copilot.data.generation.generate_feedback_topic_series`/`DRIFT_CURRENT_INDEX`, `pricing_copilot.drift.statistics.*`, `Settings.drift`.
- Produces: `detect_data_drift(settings: Settings) -> list[DriftAlert]` - one `DriftAlert` per `DriftDomain` (6 total), `category=DriftAlertCategory.DATA`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift_data_detector.py
from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlertCategory, DriftDomain
from pricing_copilot.drift.data_detector import detect_data_drift


def test_detect_data_drift_returns_one_alert_per_domain(tmp_path) -> None:
    settings = Settings(analytics_database_path=tmp_path / "test.duckdb")
    alerts = detect_data_drift(settings)
    domains = {alert.domain for alert in alerts}
    assert domains == set(DriftDomain)
    assert all(alert.category is DriftAlertCategory.DATA for alert in alerts)


def test_detect_data_drift_flags_claim_severity_as_breached() -> None:
    settings = Settings(analytics_database_path=Settings().analytics_database_path)
    alerts = detect_data_drift(settings)
    severity_alert = next(a for a in alerts if a.domain is DriftDomain.CLAIM_SEVERITY)
    assert severity_alert.breached is True
    assert severity_alert.investigation_required is True
    assert severity_alert.measurements


def test_detect_data_drift_flags_feedback_topics_via_psi() -> None:
    settings = Settings(analytics_database_path=Settings().analytics_database_path)
    alerts = detect_data_drift(settings)
    feedback_alert = next(a for a in alerts if a.domain is DriftDomain.FEEDBACK_TOPICS)
    assert feedback_alert.breached is True
    kinds = {m.measure_kind.value for m in feedback_alert.measurements}
    assert "population_stability_index" in kinds
```

Note: the second and third tests deliberately use the real, default `analytics_database_path` (not a fresh `tmp_path`) so the persistent DuckDB build runs once and is reused - matches the pattern already used by `tests/test_data_generation.py`'s scenario tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_drift_data_detector.py -v`
Expected: FAIL - `pricing_copilot.drift.data_detector` does not exist.

- [ ] **Step 3: Implement**

Create `src/pricing_copilot/drift/data_detector.py`:

```python
from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.generation import DRIFT_CURRENT_INDEX, generate_feedback_topic_series
from pricing_copilot.data.persistent import PersistentAnalyticsDatabase
from pricing_copilot.drift.contracts import (
    DriftAlert,
    DriftAlertCategory,
    DriftDomain,
    DriftMeasureKind,
    DriftMeasurement,
)
from pricing_copilot.drift.statistics import (
    kolmogorov_smirnov,
    percentage_movement,
    population_stability_index,
    rolling_z_score,
)

BASELINE_START_INDEX = 12
BASELINE_END_INDEX = 24  # exclusive
BASELINE_WINDOW_LABEL = "months 13-24"
CURRENT_WINDOW_LABEL = "month 25"


def _z_and_movement_alert(
    *,
    domain: DriftDomain,
    baseline: list[float],
    current_value: float,
    unit: str,
    settings: Settings,
) -> DriftAlert:
    policy = settings.drift
    if len(baseline) < policy.minimum_baseline_months:
        return DriftAlert(
            category=DriftAlertCategory.DATA,
            metric_name=domain.value,
            domain=domain,
            breached=False,
            investigation_required=False,
            insufficient_sample=True,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Fewer than {policy.minimum_baseline_months} baseline months are available.",
        )
    baseline_mean = sum(baseline) / len(baseline)
    z_score = rolling_z_score(baseline, current_value)
    movement = percentage_movement(baseline_mean, current_value)
    z_breached = abs(z_score) > policy.z_score_threshold
    movement_breached = abs(movement) > policy.percentage_movement_threshold_pct
    breached = z_breached or movement_breached
    measurements = [
        DriftMeasurement(
            measure_kind=DriftMeasureKind.ROLLING_Z_SCORE,
            value=round(z_score, 4),
            unit="standard deviations",
            threshold=policy.z_score_threshold,
            breached=z_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL}",
        ),
        DriftMeasurement(
            measure_kind=DriftMeasureKind.PERCENTAGE_MOVEMENT,
            value=round(movement, 2),
            unit="%",
            threshold=policy.percentage_movement_threshold_pct,
            breached=movement_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL}",
        ),
    ]
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=domain.value,
        domain=domain,
        measurements=measurements,
        breached=breached,
        investigation_required=breached,
        confidence_impact=0.4 if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=(
            f"{domain.value.replace('_', ' ').title()} moved {round(movement, 1)}% "
            f"({round(z_score, 2)} standard deviations) between {BASELINE_WINDOW_LABEL} and "
            f"{CURRENT_WINDOW_LABEL}, {unit} basis."
        ),
    )


def _claims_metrics(database: PersistentAnalyticsDatabase) -> tuple[list, list, list]:
    result = database.query_source(
        "claims",
        ScenarioName.DRIFT_MONITORING,
        columns=("period", "claim_count", "incurred_loss_gbp", "earned_premium_gbp", "policies_in_force"),
    )
    rows = sorted(result.rows, key=lambda row: row[0])
    severities = [row[2] / row[1] for row in rows]
    frequencies = [row[1] / row[4] for row in rows]
    loss_ratios = [row[2] / row[3] for row in rows]
    return severities, frequencies, loss_ratios


def _conversion_metric(database: PersistentAnalyticsDatabase) -> list[float]:
    result = database.query_source(
        "conversion",
        ScenarioName.DRIFT_MONITORING,
        columns=("period", "quotes", "sales"),
    )
    rows = sorted(result.rows, key=lambda row: row[0])
    return [row[2] / row[1] for row in rows]


def _competitor_readings(
    database: PersistentAnalyticsDatabase,
) -> tuple[list[float], list[float], list[float], list[float]]:
    result = database.query_source(
        "competitors", ScenarioName.DRIFT_MONITORING, columns=("period", "price_index")
    )
    rows = sorted(result.rows, key=lambda row: row[0])
    periods = sorted({row[0] for row in rows})
    by_period: dict = {period: [] for period in periods}
    for period, price_index in rows:
        by_period[period].append(price_index)
    ordered_periods = periods
    baseline_periods = ordered_periods[BASELINE_START_INDEX:BASELINE_END_INDEX]
    current_period = ordered_periods[DRIFT_CURRENT_INDEX]
    baseline_all = [value for period in baseline_periods for value in by_period[period]]
    current_all = by_period[current_period]
    baseline_monthly_means = [
        sum(by_period[period]) / len(by_period[period]) for period in baseline_periods
    ]
    current_mean = sum(current_all) / len(current_all)
    return baseline_all, current_all, baseline_monthly_means, [current_mean]


def _competitor_alert(database: PersistentAnalyticsDatabase, settings: Settings) -> DriftAlert:
    baseline_all, current_all, baseline_monthly_means, current_mean = _competitor_readings(database)
    policy = settings.drift
    if len(baseline_monthly_means) < policy.minimum_baseline_months:
        return DriftAlert(
            category=DriftAlertCategory.DATA,
            metric_name=DriftDomain.COMPETITOR_INDEX.value,
            domain=DriftDomain.COMPETITOR_INDEX,
            breached=False,
            investigation_required=False,
            insufficient_sample=True,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Fewer than {policy.minimum_baseline_months} baseline months are available.",
        )
    movement = percentage_movement(
        sum(baseline_monthly_means) / len(baseline_monthly_means), current_mean[0]
    )
    statistic, p_value = kolmogorov_smirnov(baseline_all, current_all)
    movement_breached = abs(movement) > policy.percentage_movement_threshold_pct
    ks_breached = p_value < policy.ks_p_value_threshold
    breached = movement_breached or ks_breached
    measurements = [
        DriftMeasurement(
            measure_kind=DriftMeasureKind.PERCENTAGE_MOVEMENT,
            value=round(movement, 2),
            unit="%",
            threshold=policy.percentage_movement_threshold_pct,
            breached=movement_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL}",
        ),
        DriftMeasurement(
            measure_kind=DriftMeasureKind.KOLMOGOROV_SMIRNOV,
            value=round(p_value, 6),
            unit="p-value",
            threshold=policy.ks_p_value_threshold,
            breached=ks_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL} (KS statistic {round(statistic, 3)})",
        ),
    ]
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=DriftDomain.COMPETITOR_INDEX.value,
        domain=DriftDomain.COMPETITOR_INDEX,
        measurements=measurements,
        breached=breached,
        investigation_required=breached,
        confidence_impact=0.3 if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=f"Competitor price index moved {round(movement, 1)}%; KS p-value {round(p_value, 4)}.",
    )


def _feedback_topics_alert(settings: Settings) -> DriftAlert:
    series = generate_feedback_topic_series()
    baseline = series[BASELINE_START_INDEX:BASELINE_END_INDEX]
    current = series[DRIFT_CURRENT_INDEX]
    policy = settings.drift
    if len(baseline) < policy.minimum_baseline_months:
        return DriftAlert(
            category=DriftAlertCategory.DATA,
            metric_name=DriftDomain.FEEDBACK_TOPICS.value,
            domain=DriftDomain.FEEDBACK_TOPICS,
            breached=False,
            investigation_required=False,
            insufficient_sample=True,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Fewer than {policy.minimum_baseline_months} baseline months are available.",
        )
    baseline_shares = [
        sum(r.claims_handling_share_pct for r in baseline) / len(baseline) / 100,
        sum(r.price_share_pct for r in baseline) / len(baseline) / 100,
        sum(r.communication_share_pct for r in baseline) / len(baseline) / 100,
        sum(r.other_share_pct for r in baseline) / len(baseline) / 100,
    ]
    current_shares = [
        current.claims_handling_share_pct / 100,
        current.price_share_pct / 100,
        current.communication_share_pct / 100,
        current.other_share_pct / 100,
    ]
    psi = population_stability_index(baseline_shares, current_shares)
    baseline_price = sum(r.price_share_pct for r in baseline) / len(baseline)
    movement = percentage_movement(baseline_price, current.price_share_pct)
    psi_breached = psi > policy.psi_threshold
    movement_breached = abs(movement) > policy.percentage_movement_threshold_pct
    breached = psi_breached or movement_breached
    measurements = [
        DriftMeasurement(
            measure_kind=DriftMeasureKind.POPULATION_STABILITY_INDEX,
            value=round(psi, 4),
            unit="PSI",
            threshold=policy.psi_threshold,
            breached=psi_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL} average topic mix",
        ),
        DriftMeasurement(
            measure_kind=DriftMeasureKind.PERCENTAGE_MOVEMENT,
            value=round(movement, 2),
            unit="%",
            threshold=policy.percentage_movement_threshold_pct,
            breached=movement_breached,
            comparison_period=f"{CURRENT_WINDOW_LABEL} vs {BASELINE_WINDOW_LABEL} (price-related share)",
        ),
    ]
    return DriftAlert(
        category=DriftAlertCategory.DATA,
        metric_name=DriftDomain.FEEDBACK_TOPICS.value,
        domain=DriftDomain.FEEDBACK_TOPICS,
        measurements=measurements,
        breached=breached,
        investigation_required=breached,
        confidence_impact=0.3 if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=f"Feedback topic mix PSI is {round(psi, 3)}; price-related share moved {round(movement, 1)}%.",
    )


def detect_data_drift(settings: Settings) -> list[DriftAlert]:
    database = PersistentAnalyticsDatabase(settings.analytics_database_path)
    severities, frequencies, loss_ratios = _claims_metrics(database)
    conversions = _conversion_metric(database)

    def baseline_and_current(series: list[float]) -> tuple[list[float], float]:
        return series[BASELINE_START_INDEX:BASELINE_END_INDEX], series[DRIFT_CURRENT_INDEX]

    severity_baseline, severity_current = baseline_and_current(severities)
    frequency_baseline, frequency_current = baseline_and_current(frequencies)
    loss_ratio_baseline, loss_ratio_current = baseline_and_current(loss_ratios)
    conversion_baseline, conversion_current = baseline_and_current(conversions)

    return [
        _z_and_movement_alert(
            domain=DriftDomain.CLAIM_SEVERITY,
            baseline=severity_baseline,
            current_value=severity_current,
            unit="GBP per claim",
            settings=settings,
        ),
        _z_and_movement_alert(
            domain=DriftDomain.CLAIM_FREQUENCY,
            baseline=frequency_baseline,
            current_value=frequency_current,
            unit="claims per policy",
            settings=settings,
        ),
        _z_and_movement_alert(
            domain=DriftDomain.LOSS_RATIO,
            baseline=loss_ratio_baseline,
            current_value=loss_ratio_current,
            unit="incurred loss / earned premium",
            settings=settings,
        ),
        _z_and_movement_alert(
            domain=DriftDomain.CONVERSION,
            baseline=conversion_baseline,
            current_value=conversion_current,
            unit="sales / quotes",
            settings=settings,
        ),
        _competitor_alert(database, settings),
        _feedback_topics_alert(settings),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_drift_data_detector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/drift/data_detector.py tests/test_drift_data_detector.py
git commit -m "feat: add the data drift detector covering all six required domains"
```

---

### Task 5: Track recommendation action and real tool-failure/retry counts on CaseResult

**Files:**
- Modify: `src/pricing_copilot/evaluation/contracts.py` (add `CaseResult.action`)
- Modify: `src/pricing_copilot/evaluation/runner.py` (populate `action` and real `tool_call_failures` from trace events)
- Test: `tests/test_evaluation_runner.py`

**Interfaces:**
- Consumes: `pricing_copilot.contracts.RecommendationAction`, `pricing_copilot.observability.contracts.TraceEventKind`.
- Produces: `CaseResult.action: RecommendationAction | None = None`, populated whenever a case resolves a recommendation; `CaseResult.tool_call_failures` now reflects real `RETRY`/`FAILURE` trace-event counts instead of always being `0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evaluation_runner.py (add to the existing file)
def test_deterministic_only_case_set_leaves_action_and_tool_failures_at_their_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pricing_copilot.evaluation import golden_set
    from pricing_copilot.evaluation.contracts import CaseKind

    deterministic_only = [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC]
    monkeypatch.setattr("pricing_copilot.evaluation.runner.GOLDEN_CASES", deterministic_only)

    report = run_benchmark(get_settings(), include_baseline=False)

    assert all(result.action is None for result in report.governed.case_results)
    assert all(result.tool_call_failures == 0 for result in report.governed.case_results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evaluation_runner.py -k action_and_tool_failures -v`
Expected: FAIL - `CaseResult` has no attribute `action` yet (AttributeError from the test's own access, or the field simply does not exist so the test itself would error at `result.action`).

- [ ] **Step 3: Implement**

In `src/pricing_copilot/evaluation/contracts.py`, add the import and field:

```python
from pricing_copilot.contracts import (
    ConfigurationVersions,
    EvidenceDomain,
    PortfolioQuestion,
    RecommendationAction,
)
```

(`RecommendationAction` is already imported for `GoldenCase.expected_actions` - just add the field to `CaseResult`:)

```python
class CaseResult(BaseModel):
    case_id: str
    category: CaseCategory
    architecture: str
    outcome: CaseOutcome
    duration_ms: float
    failure_reasons: list[str] = Field(default_factory=list)
    trace_id: str | None = None
    action: RecommendationAction | None = None
    tool_call_total: int = 0
    tool_call_failures: int = 0
    total_tokens: int = 0
    estimated_cost_gbp: float = 0.0
```

In `src/pricing_copilot/evaluation/runner.py`, add the import:

```python
from pricing_copilot.observability.contracts import TraceEventKind
```

Add a helper and use it in both `_run_chat_case` and `_run_pricing_workflow_case`:

```python
def _tool_call_failures(execution_trace) -> int:
    if execution_trace is None:
        return 0
    return sum(
        1
        for event in execution_trace.events
        if event.kind in (TraceEventKind.RETRY, TraceEventKind.FAILURE)
    )
```

In `_run_chat_case`, after the existing `trace_id`/`usage` extraction, add:

```python
    action = (
        response.workflow_result.recommendation.action
        if response.workflow_result is not None
        else None
    )
```

and update the returned `CaseResult` to include `action=action, tool_call_failures=_tool_call_failures(response.workflow_result.execution_trace if response.workflow_result else None),`.

In `_run_pricing_workflow_case`, update the returned `CaseResult` to include `action=result.recommendation.action, tool_call_failures=_tool_call_failures(result.execution_trace),`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_evaluation_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full evaluation test suite to catch any signature drift**

Run: `uv run pytest tests/test_evaluation_contracts.py tests/test_evaluation_runner.py tests/test_evaluation_scoring.py tests/test_evaluation_store.py tests/test_evaluation_golden_set.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pricing_copilot/evaluation/contracts.py src/pricing_copilot/evaluation/runner.py tests/test_evaluation_runner.py
git commit -m "feat: record the recommendation action and real tool-failure counts on CaseResult"
```

---

### Task 6: Behavior and operational drift detectors

**Files:**
- Create: `src/pricing_copilot/drift/behavior_detector.py`
- Create: `src/pricing_copilot/drift/operational_detector.py`
- Test: `tests/test_drift_behavior_detector.py`
- Test: `tests/test_drift_operational_detector.py`

**Interfaces:**
- Consumes: `pricing_copilot.evaluation.contracts.BenchmarkReport`, `Settings.drift`, `CaseResult.action` (from Task 5).
- Produces: `detect_behavior_drift(report: BenchmarkReport, settings: Settings) -> list[DriftAlert]`; `detect_operational_drift(report: BenchmarkReport, settings: Settings) -> list[DriftAlert]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_drift_behavior_detector.py
from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.contracts import RecommendationAction
from pricing_copilot.drift.behavior_detector import detect_behavior_drift
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    CaseCategory,
    CaseOutcome,
    CaseResult,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.versions import current_configuration_versions


def _report(actuals: EvaluationActuals, case_results: list[CaseResult]) -> BenchmarkReport:
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=case_results,
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(Settings()),
        governed=governed,
    )


def _actuals(**overrides) -> EvaluationActuals:
    base = dict(
        deterministic_accuracy_pct=100.0,
        output_schema_valid_pct=100.0,
        citation_coverage_pct=100.0,
        ambiguous_abstention_pct=100.0,
        prompt_injection_success_pct=0.0,
        critical_guardrail_pass_pct=100.0,
        specialist_routing_accuracy_pct=100.0,
        unsupported_recommendation_count=0,
        latency_p95_seconds=10.0,
        tool_call_failure_pct=0.0,
        total_estimated_cost_gbp=0.0,
        total_tokens=0,
        governance_rejection_count=0,
        safe_abstention_count=0,
        cases_passed=10,
        cases_failed=0,
        cases_errored=0,
    )
    base.update(overrides)
    return EvaluationActuals(**base)


def test_detect_behavior_drift_flags_low_routing_accuracy() -> None:
    report = _report(_actuals(specialist_routing_accuracy_pct=50.0), [])
    alerts = detect_behavior_drift(report, Settings())
    routing_alert = next(a for a in alerts if a.metric_name == "specialist_routing_accuracy_pct")
    assert routing_alert.category is DriftAlertCategory.BEHAVIOR
    assert routing_alert.breached is True


def test_detect_behavior_drift_reports_recommendation_distribution() -> None:
    case_results = [
        CaseResult(
            case_id="GC-1", category=CaseCategory.NORMAL, architecture="governed",
            outcome=CaseOutcome.PASSED, duration_ms=1.0, action=RecommendationAction.INCREASE,
        ),
        CaseResult(
            case_id="GC-2", category=CaseCategory.NORMAL, architecture="governed",
            outcome=CaseOutcome.PASSED, duration_ms=1.0, action=RecommendationAction.HOLD,
        ),
    ]
    report = _report(_actuals(), case_results)
    alerts = detect_behavior_drift(report, Settings())
    distribution_alert = next(a for a in alerts if a.metric_name == "recommendation_distribution")
    assert "increase" in distribution_alert.detail
    assert "hold" in distribution_alert.detail
```

```python
# tests/test_drift_operational_detector.py
from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.drift.operational_detector import detect_operational_drift
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.versions import current_configuration_versions


def _actuals(**overrides) -> EvaluationActuals:
    base = dict(
        deterministic_accuracy_pct=100.0,
        output_schema_valid_pct=100.0,
        citation_coverage_pct=100.0,
        ambiguous_abstention_pct=100.0,
        prompt_injection_success_pct=0.0,
        critical_guardrail_pass_pct=100.0,
        specialist_routing_accuracy_pct=100.0,
        unsupported_recommendation_count=0,
        latency_p95_seconds=10.0,
        tool_call_failure_pct=0.0,
        total_estimated_cost_gbp=0.0,
        total_tokens=0,
        governance_rejection_count=0,
        safe_abstention_count=0,
        cases_passed=10,
        cases_failed=0,
        cases_errored=0,
    )
    base.update(overrides)
    return EvaluationActuals(**base)


def _report(actuals: EvaluationActuals) -> BenchmarkReport:
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=[],
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(Settings()),
        governed=governed,
    )


def test_detect_operational_drift_flags_high_latency() -> None:
    report = _report(_actuals(latency_p95_seconds=60.0))
    alerts = detect_operational_drift(report, Settings())
    latency_alert = next(a for a in alerts if a.metric_name == "latency_p95_seconds")
    assert latency_alert.category is DriftAlertCategory.OPERATIONAL
    assert latency_alert.breached is True


def test_detect_operational_drift_passes_when_within_ceilings() -> None:
    report = _report(_actuals())
    alerts = detect_operational_drift(report, Settings())
    assert all(not a.breached for a in alerts if a.metric_name != "token_and_cost_usage")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_drift_behavior_detector.py tests/test_drift_operational_detector.py -v`
Expected: FAIL - modules do not exist.

- [ ] **Step 3: Implement**

Create `src/pricing_copilot/drift/behavior_detector.py`:

```python
from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory
from pricing_copilot.evaluation.contracts import BenchmarkReport

BASELINE_WINDOW_LABEL = "golden-suite target"
CURRENT_WINDOW_LABEL = "latest governed benchmark run"


def _floor_alert(metric_name: str, actual: float, floor: float, impact: float) -> DriftAlert:
    breached = actual < floor
    return DriftAlert(
        category=DriftAlertCategory.BEHAVIOR,
        metric_name=metric_name,
        breached=breached,
        investigation_required=breached,
        confidence_impact=impact if breached else 0.0,
        baseline_window=BASELINE_WINDOW_LABEL,
        current_window=CURRENT_WINDOW_LABEL,
        detail=f"{metric_name} is {actual}%, floor is {floor}%.",
    )


def detect_behavior_drift(report: BenchmarkReport, settings: Settings) -> list[DriftAlert]:
    actuals = report.governed.actuals
    policy = settings.drift
    alerts = [
        _floor_alert(
            "specialist_routing_accuracy_pct",
            actuals.specialist_routing_accuracy_pct,
            policy.routing_accuracy_floor_pct,
            0.3,
        ),
        _floor_alert(
            "citation_coverage_pct", actuals.citation_coverage_pct, policy.citation_coverage_floor_pct, 0.3
        ),
        _floor_alert(
            "ambiguous_abstention_pct",
            actuals.ambiguous_abstention_pct,
            policy.safe_abstention_floor_pct,
            0.3,
        ),
    ]

    rejection_breached = actuals.governance_rejection_count > policy.governance_rejection_ceiling_count
    alerts.append(
        DriftAlert(
            category=DriftAlertCategory.BEHAVIOR,
            metric_name="governance_rejection_count",
            breached=rejection_breached,
            investigation_required=rejection_breached,
            confidence_impact=0.2 if rejection_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Governance rejections: {actuals.governance_rejection_count}, "
                f"ceiling is {policy.governance_rejection_ceiling_count}."
            ),
        )
    )

    total_cases = actuals.cases_passed + actuals.cases_failed + actuals.cases_errored
    pass_rate = (100.0 * actuals.cases_passed / total_cases) if total_cases else 0.0
    suite_breached = pass_rate < policy.golden_suite_pass_floor_pct
    alerts.append(
        DriftAlert(
            category=DriftAlertCategory.BEHAVIOR,
            metric_name="golden_suite_pass_rate_pct",
            breached=suite_breached,
            investigation_required=suite_breached,
            confidence_impact=0.4 if suite_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Golden-suite pass rate is {round(pass_rate, 2)}%, "
                f"floor is {policy.golden_suite_pass_floor_pct}%."
            ),
        )
    )

    distribution: dict[str, int] = {}
    for result in report.governed.case_results:
        if result.action is not None:
            distribution[result.action.value] = distribution.get(result.action.value, 0) + 1
    alerts.append(
        DriftAlert(
            category=DriftAlertCategory.BEHAVIOR,
            metric_name="recommendation_distribution",
            breached=False,
            investigation_required=False,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Recommendation action distribution across governed cases: {distribution}.",
        )
    )
    return alerts
```

Create `src/pricing_copilot/drift/operational_detector.py`:

```python
from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory
from pricing_copilot.evaluation.contracts import BenchmarkReport

BASELINE_WINDOW_LABEL = "operational policy ceiling"
CURRENT_WINDOW_LABEL = "latest governed benchmark run"


def detect_operational_drift(report: BenchmarkReport, settings: Settings) -> list[DriftAlert]:
    actuals = report.governed.actuals
    policy = settings.drift

    latency_breached = actuals.latency_p95_seconds > policy.latency_p95_ceiling_seconds
    tool_failure_breached = actuals.tool_call_failure_pct > policy.tool_failure_ceiling_pct
    invalid_output_breached = actuals.output_schema_valid_pct < 100.0

    return [
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="latency_p95_seconds",
            breached=latency_breached,
            investigation_required=latency_breached,
            confidence_impact=0.2 if latency_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"P95 latency is {actuals.latency_p95_seconds}s, "
                f"ceiling is {policy.latency_p95_ceiling_seconds}s."
            ),
        ),
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="tool_call_failure_pct",
            breached=tool_failure_breached,
            investigation_required=tool_failure_breached,
            confidence_impact=0.2 if tool_failure_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Tool call failure rate is {actuals.tool_call_failure_pct}%, "
                f"ceiling is {policy.tool_failure_ceiling_pct}%."
            ),
        ),
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="output_schema_valid_pct",
            breached=invalid_output_breached,
            investigation_required=invalid_output_breached,
            confidence_impact=0.3 if invalid_output_breached else 0.0,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"Output schema validity is {actuals.output_schema_valid_pct}%, target is 100%.",
        ),
        DriftAlert(
            category=DriftAlertCategory.OPERATIONAL,
            metric_name="token_and_cost_usage",
            breached=False,
            investigation_required=False,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=(
                f"Total tokens: {actuals.total_tokens}, "
                f"estimated cost: GBP {actuals.total_estimated_cost_gbp}."
            ),
        ),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_drift_behavior_detector.py tests/test_drift_operational_detector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/drift/behavior_detector.py src/pricing_copilot/drift/operational_detector.py tests/test_drift_behavior_detector.py tests/test_drift_operational_detector.py
git commit -m "feat: add behavior and operational drift detectors"
```

---

### Task 7: Configuration drift detector

**Files:**
- Create: `src/pricing_copilot/drift/configuration_detector.py`
- Test: `tests/test_drift_configuration_detector.py`

**Interfaces:**
- Consumes: `pricing_copilot.contracts.ConfigurationVersions`.
- Produces: `detect_configuration_drift(previous: ConfigurationVersions | None, current: ConfigurationVersions) -> list[DriftAlert]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift_configuration_detector.py
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.configuration_detector import detect_configuration_drift


def _versions(**overrides) -> ConfigurationVersions:
    base = dict(
        model_name="gpt-test",
        recommendation_version="v1",
        governance_version="v1",
        scenario_seed=1,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )
    base.update(overrides)
    return ConfigurationVersions(**base)


def test_detect_configuration_drift_flags_no_previous_snapshot_as_insufficient_sample() -> None:
    alerts = detect_configuration_drift(None, _versions())
    assert len(alerts) == 1
    assert alerts[0].insufficient_sample is True
    assert alerts[0].breached is False


def test_detect_configuration_drift_reports_no_change_when_identical() -> None:
    versions = _versions()
    alerts = detect_configuration_drift(versions, versions)
    assert len(alerts) == 1
    assert alerts[0].breached is False


def test_detect_configuration_drift_flags_every_changed_field() -> None:
    previous = _versions(model_name="gpt-old")
    current = _versions(model_name="gpt-new")
    alerts = detect_configuration_drift(previous, current)
    changed = next(a for a in alerts if a.metric_name == "model_name")
    assert changed.breached is True
    assert changed.investigation_required is True
    assert "gpt-old" in changed.detail
    assert "gpt-new" in changed.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_drift_configuration_detector.py -v`
Expected: FAIL - module does not exist.

- [ ] **Step 3: Implement**

Create `src/pricing_copilot/drift/configuration_detector.py`:

```python
from __future__ import annotations

from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory

BASELINE_WINDOW_LABEL = "previously recorded configuration"
CURRENT_WINDOW_LABEL = "current configuration"


def detect_configuration_drift(
    previous: ConfigurationVersions | None, current: ConfigurationVersions
) -> list[DriftAlert]:
    if previous is None:
        return [
            DriftAlert(
                category=DriftAlertCategory.CONFIGURATION,
                metric_name="configuration_baseline",
                breached=False,
                investigation_required=False,
                insufficient_sample=True,
                baseline_window=BASELINE_WINDOW_LABEL,
                current_window=CURRENT_WINDOW_LABEL,
                detail="No previous configuration snapshot exists yet; this run establishes the baseline.",
            )
        ]

    previous_fields = previous.model_dump()
    current_fields = current.model_dump()
    changed = {
        field: (previous_fields[field], current_fields[field])
        for field in current_fields
        if previous_fields.get(field) != current_fields[field]
    }
    if not changed:
        return [
            DriftAlert(
                category=DriftAlertCategory.CONFIGURATION,
                metric_name="configuration_versions",
                breached=False,
                investigation_required=False,
                baseline_window=BASELINE_WINDOW_LABEL,
                current_window=CURRENT_WINDOW_LABEL,
                detail="No configuration fields changed since the previous snapshot.",
            )
        ]

    return [
        DriftAlert(
            category=DriftAlertCategory.CONFIGURATION,
            metric_name=field,
            breached=True,
            investigation_required=True,
            confidence_impact=0.1,
            baseline_window=BASELINE_WINDOW_LABEL,
            current_window=CURRENT_WINDOW_LABEL,
            detail=f"{field} changed from {old_value!r} to {new_value!r}.",
        )
        for field, (old_value, new_value) in changed.items()
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_drift_configuration_detector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/drift/configuration_detector.py tests/test_drift_configuration_detector.py
git commit -m "feat: add the configuration drift detector"
```

---

### Task 8: Drift report storage and the top-level monitor

**Files:**
- Create: `src/pricing_copilot/drift/store.py`
- Create: `src/pricing_copilot/drift/monitor.py`
- Modify: `.gitignore` (carve out `var/drift/` alongside the existing `var/replay/`/`var/evaluation/` pattern)
- Test: `tests/test_drift_store.py`
- Test: `tests/test_drift_monitor.py`

**Interfaces:**
- Consumes: all four detectors from Tasks 4, 6, 7; `pricing_copilot.versions.current_configuration_versions`.
- Produces: `save_drift_report`/`load_drift_report`/`save_previous_configuration`/`load_previous_configuration`; `run_drift_monitoring(settings: Settings, benchmark_report: BenchmarkReport) -> DriftReport`; `DRIFT_REPORT_VERSION`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_drift_store.py
from pricing_copilot.config import Settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import DriftReport
from pricing_copilot.drift.store import (
    load_drift_report,
    load_previous_configuration,
    save_drift_report,
    save_previous_configuration,
)


def _versions() -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name="gpt-test",
        recommendation_version="v1",
        governance_version="v1",
        scenario_seed=1,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )


def test_drift_report_round_trips_through_disk(tmp_path) -> None:
    from datetime import UTC, datetime

    settings = Settings(drift_directory=tmp_path / "drift")
    report = DriftReport(
        report_version="drift-report-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=_versions(),
        alerts=[],
    )
    save_drift_report(report, settings)
    loaded = load_drift_report(settings)
    assert loaded is not None
    assert loaded.report_version == "drift-report-v1"


def test_load_drift_report_returns_none_when_absent(tmp_path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    assert load_drift_report(settings) is None


def test_previous_configuration_round_trips_through_disk(tmp_path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    assert load_previous_configuration(settings) is None
    save_previous_configuration(_versions(), settings)
    loaded = load_previous_configuration(settings)
    assert loaded is not None
    assert loaded.model_name == "gpt-test"
```

```python
# tests/test_drift_monitor.py
from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.drift.monitor import run_drift_monitoring
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.versions import current_configuration_versions


def _benchmark_report(settings: Settings) -> BenchmarkReport:
    actuals = EvaluationActuals(
        deterministic_accuracy_pct=100.0,
        output_schema_valid_pct=100.0,
        citation_coverage_pct=100.0,
        ambiguous_abstention_pct=100.0,
        prompt_injection_success_pct=0.0,
        critical_guardrail_pass_pct=100.0,
        specialist_routing_accuracy_pct=100.0,
        unsupported_recommendation_count=0,
        latency_p95_seconds=10.0,
        tool_call_failure_pct=0.0,
        total_estimated_cost_gbp=0.0,
        total_tokens=0,
        governance_rejection_count=0,
        safe_abstention_count=0,
        cases_passed=10,
        cases_failed=0,
        cases_errored=0,
    )
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=[],
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(settings),
        governed=governed,
    )


def test_run_drift_monitoring_produces_alerts_across_all_four_categories(tmp_path) -> None:
    settings = Settings(drift_directory=tmp_path / "drift")
    report = run_drift_monitoring(settings, _benchmark_report(settings))
    categories = {alert.category for alert in report.alerts}
    assert categories == set(DriftAlertCategory)


def test_run_drift_monitoring_saves_the_current_configuration_for_next_time(tmp_path) -> None:
    from pricing_copilot.drift.store import load_previous_configuration

    settings = Settings(drift_directory=tmp_path / "drift")
    assert load_previous_configuration(settings) is None
    run_drift_monitoring(settings, _benchmark_report(settings))
    assert load_previous_configuration(settings) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_drift_store.py tests/test_drift_monitor.py -v`
Expected: FAIL - modules do not exist.

- [ ] **Step 3: Implement**

Create `src/pricing_copilot/drift/store.py`:

```python
from __future__ import annotations

from pathlib import Path

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.drift.contracts import DriftReport


def _report_path(settings: Settings) -> Path:
    return Path(settings.drift_directory) / "latest.json"


def _previous_configuration_path(settings: Settings) -> Path:
    return Path(settings.drift_directory) / "previous_configuration.json"


def save_drift_report(report: DriftReport, settings: Settings) -> Path:
    path = _report_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    return path


def load_drift_report(settings: Settings) -> DriftReport | None:
    path = _report_path(settings)
    if not path.exists():
        return None
    return DriftReport.model_validate_json(path.read_text())


def load_previous_configuration(settings: Settings) -> ConfigurationVersions | None:
    path = _previous_configuration_path(settings)
    if not path.exists():
        return None
    return ConfigurationVersions.model_validate_json(path.read_text())


def save_previous_configuration(versions: ConfigurationVersions, settings: Settings) -> Path:
    path = _previous_configuration_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(versions.model_dump_json(indent=2))
    return path
```

Create `src/pricing_copilot/drift/monitor.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.drift.behavior_detector import detect_behavior_drift
from pricing_copilot.drift.configuration_detector import detect_configuration_drift
from pricing_copilot.drift.contracts import DriftReport
from pricing_copilot.drift.data_detector import detect_data_drift
from pricing_copilot.drift.operational_detector import detect_operational_drift
from pricing_copilot.drift.store import load_previous_configuration, save_previous_configuration
from pricing_copilot.evaluation.contracts import BenchmarkReport
from pricing_copilot.versions import current_configuration_versions

DRIFT_REPORT_VERSION = "drift-report-v1"


def run_drift_monitoring(settings: Settings, benchmark_report: BenchmarkReport) -> DriftReport:
    current_versions = current_configuration_versions(settings)
    previous_versions = load_previous_configuration(settings)

    alerts = [
        *detect_data_drift(settings),
        *detect_behavior_drift(benchmark_report, settings),
        *detect_operational_drift(benchmark_report, settings),
        *detect_configuration_drift(previous_versions, current_versions),
    ]
    save_previous_configuration(current_versions, settings)
    return DriftReport(
        report_version=DRIFT_REPORT_VERSION,
        generated_at=datetime.now(UTC),
        configuration_versions=current_versions,
        alerts=alerts,
    )
```

In `.gitignore`, add a fourth line after `!var/evaluation/`:

```
!var/drift/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_drift_store.py tests/test_drift_monitor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/drift/store.py src/pricing_copilot/drift/monitor.py .gitignore tests/test_drift_store.py tests/test_drift_monitor.py
git commit -m "feat: add drift report storage and the top-level drift monitor"
```

---

### Task 9: Evaluated change-promotion gate

**Files:**
- Create: `src/pricing_copilot/evaluation/gate.py`
- Modify: `src/pricing_copilot/evaluation/store.py` (add `save_promoted_report`/`load_promoted_report`)
- Test: `tests/test_evaluation_gate.py`

**Interfaces:**
- Consumes: `pricing_copilot.evaluation.contracts.BenchmarkReport`/`CaseOutcome`.
- Produces: `PromotionGateResult(promoted: bool, failing_metrics: list[str], failing_case_ids: list[str], detail: str)`; `evaluate_promotion_gate(report: BenchmarkReport) -> PromotionGateResult`; `save_promoted_report`/`load_promoted_report`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evaluation_gate.py
from datetime import UTC, datetime

from pricing_copilot.config import Settings
from pricing_copilot.evaluation.contracts import (
    BenchmarkReport,
    CaseCategory,
    CaseOutcome,
    CaseResult,
    EvaluationActuals,
    EvaluationReport,
    EvaluationTargets,
)
from pricing_copilot.evaluation.gate import evaluate_promotion_gate
from pricing_copilot.evaluation.store import load_promoted_report, save_promoted_report
from pricing_copilot.versions import current_configuration_versions


def _actuals(**overrides) -> EvaluationActuals:
    base = dict(
        deterministic_accuracy_pct=100.0,
        output_schema_valid_pct=100.0,
        citation_coverage_pct=100.0,
        ambiguous_abstention_pct=100.0,
        prompt_injection_success_pct=0.0,
        critical_guardrail_pass_pct=100.0,
        specialist_routing_accuracy_pct=100.0,
        unsupported_recommendation_count=0,
        latency_p95_seconds=10.0,
        tool_call_failure_pct=0.0,
        total_estimated_cost_gbp=0.0,
        total_tokens=0,
        governance_rejection_count=0,
        safe_abstention_count=0,
        cases_passed=10,
        cases_failed=0,
        cases_errored=0,
    )
    base.update(overrides)
    return EvaluationActuals(**base)


def _report(actuals: EvaluationActuals, case_results: list[CaseResult] | None = None) -> BenchmarkReport:
    governed = EvaluationReport(
        architecture="governed",
        generated_at=datetime.now(UTC),
        targets=EvaluationTargets(),
        actuals=actuals,
        case_results=case_results or [],
    )
    return BenchmarkReport(
        report_version="benchmark-report-v1",
        golden_set_version="golden-set-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(Settings()),
        governed=governed,
    )


def test_promotion_gate_promotes_a_fully_passing_report() -> None:
    result = evaluate_promotion_gate(_report(_actuals()))
    assert result.promoted is True
    assert result.failing_metrics == []
    assert result.failing_case_ids == []


def test_promotion_gate_rejects_a_report_below_a_floor_target() -> None:
    result = evaluate_promotion_gate(_report(_actuals(specialist_routing_accuracy_pct=50.0)))
    assert result.promoted is False
    assert any("specialist_routing_accuracy_pct" in metric for metric in result.failing_metrics)


def test_promotion_gate_rejects_a_report_above_a_ceiling_target() -> None:
    result = evaluate_promotion_gate(_report(_actuals(latency_p95_seconds=999.0)))
    assert result.promoted is False
    assert any("latency_p95_seconds" in metric for metric in result.failing_metrics)


def test_promotion_gate_records_failing_case_ids() -> None:
    failing_case = CaseResult(
        case_id="GC-99", category=CaseCategory.NORMAL, architecture="governed",
        outcome=CaseOutcome.FAILED, duration_ms=1.0,
    )
    result = evaluate_promotion_gate(_report(_actuals(), [failing_case]))
    assert result.promoted is False
    assert result.failing_case_ids == ["GC-99"]


def test_promoted_report_round_trips_through_disk(tmp_path) -> None:
    settings = Settings(evaluation_directory=tmp_path / "evaluation")
    assert load_promoted_report(settings) is None
    save_promoted_report(_report(_actuals()), settings)
    loaded = load_promoted_report(settings)
    assert loaded is not None
    assert loaded.report_version == "benchmark-report-v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evaluation_gate.py -v`
Expected: FAIL - `pricing_copilot.evaluation.gate` does not exist.

- [ ] **Step 3: Implement**

Create `src/pricing_copilot/evaluation/gate.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from pricing_copilot.evaluation.contracts import BenchmarkReport, CaseOutcome

_FLOOR_METRICS = (
    "deterministic_accuracy_pct",
    "output_schema_valid_pct",
    "citation_coverage_pct",
    "ambiguous_abstention_pct",
    "critical_guardrail_pass_pct",
    "specialist_routing_accuracy_pct",
)
_CEILING_METRICS = (
    "prompt_injection_success_pct",
    "unsupported_recommendation_count",
    "latency_p95_seconds",
    "tool_call_failure_pct",
)


class PromotionGateResult(BaseModel):
    promoted: bool
    failing_metrics: list[str] = Field(default_factory=list)
    failing_case_ids: list[str] = Field(default_factory=list)
    detail: str


def evaluate_promotion_gate(report: BenchmarkReport) -> PromotionGateResult:
    actuals = report.governed.actuals
    targets = report.governed.targets
    failing_metrics: list[str] = []
    for metric in _FLOOR_METRICS:
        actual_value = getattr(actuals, metric)
        target_value = getattr(targets, metric)
        if actual_value < target_value:
            failing_metrics.append(f"{metric}: actual {actual_value} below target {target_value}")
    for metric in _CEILING_METRICS:
        actual_value = getattr(actuals, metric)
        target_value = getattr(targets, metric)
        if actual_value > target_value:
            failing_metrics.append(f"{metric}: actual {actual_value} above target {target_value}")

    failing_case_ids = [
        result.case_id
        for result in report.governed.case_results
        if result.outcome != CaseOutcome.PASSED
    ]
    promoted = not failing_metrics and not failing_case_ids
    detail = (
        "All evaluation gates passed; this report is promoted as the current default."
        if promoted
        else (
            f"{len(failing_metrics)} metric(s) and {len(failing_case_ids)} case(s) failed; "
            "the current default configuration is preserved."
        )
    )
    return PromotionGateResult(
        promoted=promoted,
        failing_metrics=failing_metrics,
        failing_case_ids=failing_case_ids,
        detail=detail,
    )
```

In `src/pricing_copilot/evaluation/store.py`, add:

```python
def _promoted_report_path(settings: Settings) -> Path:
    return Path(settings.evaluation_directory) / "promoted.json"


def save_promoted_report(report: BenchmarkReport, settings: Settings) -> Path:
    path = _promoted_report_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    return path


def load_promoted_report(settings: Settings) -> BenchmarkReport | None:
    path = _promoted_report_path(settings)
    if not path.exists():
        return None
    return BenchmarkReport.model_validate_json(path.read_text())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_evaluation_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/evaluation/gate.py src/pricing_copilot/evaluation/store.py tests/test_evaluation_gate.py
git commit -m "feat: add the evaluated change-promotion gate"
```

---

### Task 10: Drift-penalty hook in confidence calculation

**Files:**
- Modify: `src/pricing_copilot/evidence/confidence.py`
- Test: `tests/test_evidence_confidence.py`

**Interfaces:**
- Produces: `calculate_confidence(..., drift_penalty: float = 0.0) -> ConfidenceBreakdown` - backward compatible; `data_quality` now reflects `max(0.0, 1.0 - drift_penalty)` instead of a hardcoded `1.0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evidence_confidence.py (add to the existing file)
def test_drift_penalty_lowers_data_quality_and_overall_confidence():
    baseline = calculate_confidence(
        ledger=EvidenceLedger(entries=[]),
        documents=[],
        analytics=_analytics(),  # reuse whatever helper the existing tests in this file already use
        action=RecommendationAction.HOLD,
        analysis_period_end=date(2025, 12, 1),
    )
    penalized = calculate_confidence(
        ledger=EvidenceLedger(entries=[]),
        documents=[],
        analytics=_analytics(),
        action=RecommendationAction.HOLD,
        analysis_period_end=date(2025, 12, 1),
        drift_penalty=0.4,
    )
    assert penalized.data_quality < baseline.data_quality
    assert penalized.overall < baseline.overall
```

Note: read the existing `tests/test_evidence_confidence.py` first to reuse its actual analytics/ledger fixture helper names exactly (do not invent a `_analytics()` helper that does not already exist in that file - match whatever pattern the file already uses for its other test cases).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evidence_confidence.py -k drift_penalty -v`
Expected: FAIL - `calculate_confidence()` does not accept `drift_penalty`.

- [ ] **Step 3: Implement**

In `src/pricing_copilot/evidence/confidence.py`, change the signature and the `data_quality` line:

```python
def calculate_confidence(
    *,
    ledger: EvidenceLedger,
    documents: list[RetrievedDocument],
    analytics: PortfolioAnalytics,
    action: RecommendationAction,
    analysis_period_end: date,
    drift_penalty: float = 0.0,
) -> ConfidenceBreakdown:
```

Replace `data_quality = 1.0` with:

```python
    data_quality = max(0.0, 1.0 - drift_penalty)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_evidence_confidence.py -v`
Expected: PASS (all tests in the file, not just the new one).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/evidence/confidence.py tests/test_evidence_confidence.py
git commit -m "feat: let material drift lower recommendation confidence"
```

---

### Task 11: CLI --monitor-drift and --check-promotion flags

**Files:**
- Modify: `src/pricing_copilot/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `pricing_copilot.evaluation.store.load_benchmark_report`/`save_promoted_report`, `pricing_copilot.evaluation.gate.evaluate_promotion_gate`, `pricing_copilot.drift.monitor.run_drift_monitoring`, `pricing_copilot.drift.store.save_drift_report`.
- Produces: `--monitor-drift` (exit 0 on success, exit 1 if no evaluation report exists yet); `--check-promotion` (exit 0 and saves `promoted.json` if the gate passes, exit 1 and leaves `promoted.json` untouched otherwise).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py (add to the existing file)
def test_cli_monitor_drift_flag_requires_an_evaluation_report_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pricing_copilot.config import get_settings

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    monkeypatch.setenv("PRICING_COPILOT_DRIFT_DIRECTORY", str(tmp_path / "drift"))
    get_settings.cache_clear()
    try:
        exit_code = main(["--monitor-drift"])
    finally:
        get_settings.cache_clear()
    assert exit_code == 1
    assert "no evaluation report" in capsys.readouterr().err.lower()


def test_cli_monitor_drift_flag_runs_after_an_evaluation_report_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pricing_copilot.config import get_settings
    from pricing_copilot.evaluation import golden_set
    from pricing_copilot.evaluation.contracts import CaseKind
    from pricing_copilot.evaluation.runner import run_benchmark
    from pricing_copilot.evaluation.store import save_benchmark_report

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    monkeypatch.setenv("PRICING_COPILOT_DRIFT_DIRECTORY", str(tmp_path / "drift"))
    monkeypatch.setattr(
        "pricing_copilot.evaluation.runner.GOLDEN_CASES",
        [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC],
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        save_benchmark_report(run_benchmark(settings, include_baseline=False), settings)
        exit_code = main(["--monitor-drift"])
    finally:
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "material" in out.lower()
    assert (tmp_path / "drift" / "latest.json").exists()


def test_cli_check_promotion_flag_promotes_a_passing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pricing_copilot.config import get_settings
    from pricing_copilot.evaluation import golden_set
    from pricing_copilot.evaluation.contracts import CaseKind
    from pricing_copilot.evaluation.runner import run_benchmark
    from pricing_copilot.evaluation.store import save_benchmark_report

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    monkeypatch.setattr(
        "pricing_copilot.evaluation.runner.GOLDEN_CASES",
        [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC],
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        save_benchmark_report(run_benchmark(settings, include_baseline=False), settings)
        exit_code = main(["--check-promotion"])
    finally:
        get_settings.cache_clear()
    assert exit_code == 0
    assert "promoted" in capsys.readouterr().out.lower()
    assert (tmp_path / "evaluation" / "promoted.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "monitor_drift or check_promotion" -v`
Expected: FAIL - `--monitor-drift`/`--check-promotion` are not recognized arguments.

- [ ] **Step 3: Implement**

In `src/pricing_copilot/cli.py`, add to `build_parser()`:

```python
    parser.add_argument(
        "--monitor-drift",
        action="store_true",
        help="Run drift monitoring against the latest evaluation report and save a drift report.",
    )
    parser.add_argument(
        "--check-promotion",
        action="store_true",
        help="Check the latest evaluation report against its targets and promote it if it passes.",
    )
```

In `main()`, add two new branches (after the existing `if args.evaluate:` block, before the `required_arguments` check):

```python
    if args.monitor_drift:
        from pricing_copilot.drift.monitor import run_drift_monitoring
        from pricing_copilot.drift.store import save_drift_report
        from pricing_copilot.evaluation.store import load_benchmark_report

        benchmark_report = load_benchmark_report(get_settings())
        if benchmark_report is None:
            print(
                "No evaluation report is recorded yet. Run --evaluate first.", file=sys.stderr
            )
            return 1
        drift_report = run_drift_monitoring(get_settings(), benchmark_report)
        path = save_drift_report(drift_report, get_settings())
        material = drift_report.material_alerts
        print(f"Drift report: {len(drift_report.alerts)} alert(s), {len(material)} material.")
        for alert in material:
            print(f"  - {alert.category.value}/{alert.metric_name}: {alert.detail}")
        print(f"Saved to {path}")
        return 0

    if args.check_promotion:
        from pricing_copilot.evaluation.gate import evaluate_promotion_gate
        from pricing_copilot.evaluation.store import load_benchmark_report, save_promoted_report

        benchmark_report = load_benchmark_report(get_settings())
        if benchmark_report is None:
            print(
                "No evaluation report is recorded yet. Run --evaluate first.", file=sys.stderr
            )
            return 1
        result = evaluate_promotion_gate(benchmark_report)
        if result.promoted:
            path = save_promoted_report(benchmark_report, get_settings())
            print(f"Promoted: {result.detail} Saved to {path}")
            return 0
        print(f"Not promoted: {result.detail}", file=sys.stderr)
        for metric in result.failing_metrics:
            print(f"  - failing metric: {metric}", file=sys.stderr)
        for case_id in result.failing_case_ids:
            print(f"  - failing case: {case_id}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/cli.py tests/test_cli.py
git commit -m "feat: add --monitor-drift and --check-promotion CLI flags"
```

---

### Task 12: Wire the chat DRIFT intent to the real drift report

**Files:**
- Modify: `src/pricing_copilot/chat/service.py`
- Test: `tests/test_chat_service.py`

**Interfaces:**
- Consumes: `pricing_copilot.drift.store.load_drift_report`.
- Produces: `ChatService._report_drift(context, listener) -> ChatResponse`, dispatched from `submit()` for `ChatIntent.DRIFT`, replacing the current permanent stub.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_service.py (add to the existing file)
def test_drift_intent_reports_no_report_recorded_yet_honestly(service: ChatService) -> None:
    response = service.submit("Show me drift monitoring", ChatContext())
    assert response.intent is ChatIntent.DRIFT
    assert "no drift monitoring run" in response.message.lower()


def test_drift_intent_reports_material_alerts_from_a_saved_report(service: ChatService) -> None:
    from datetime import UTC, datetime

    from pricing_copilot.drift.contracts import DriftAlert, DriftAlertCategory, DriftReport
    from pricing_copilot.drift.store import save_drift_report
    from pricing_copilot.versions import current_configuration_versions

    report = DriftReport(
        report_version="drift-report-v1",
        generated_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(service.settings),
        alerts=[
            DriftAlert(
                category=DriftAlertCategory.DATA,
                metric_name="claim_severity",
                breached=True,
                investigation_required=True,
                baseline_window="months 13-24",
                current_window="month 25",
                detail="Claim severity moved sharply.",
            )
        ],
    )
    save_drift_report(report, service.settings)

    response = service.submit("Show me drift monitoring", ChatContext())
    assert response.intent is ChatIntent.DRIFT
    assert "1 measure" in response.message.lower() or "1 measure(s)" in response.message.lower()
    assert response.tables
```

Note: the `service` fixture in this file must construct `Settings` with `drift_directory=tmp_path / "drift"` alongside its existing `replay_directory`/`evaluation_directory` overrides - follow the exact same isolation pattern already used for those two, to avoid writing into the real committed `var/drift/` directory (this was a real bug found and fixed twice already in this repository's history, for replay and evaluation).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_service.py -k drift_intent -v`
Expected: FAIL - the stub message does not match.

- [ ] **Step 3: Implement**

First, update the `service` fixture at the top of `tests/test_chat_service.py` to add `drift_directory=tmp_path / "drift"`.

In `src/pricing_copilot/chat/service.py`, replace the `ChatIntent.DRIFT` branch in `submit()`:

```python
        if intent is ChatIntent.DRIFT:
            return self._report_drift(active_context, on_activity)
```

Add the handler method (place it after `_report_evaluation`):

```python
    def _report_drift(
        self, context: ChatContext, listener: ActivityListener | None
    ) -> ChatResponse:
        from pricing_copilot.drift.store import load_drift_report

        activities: list[ChatActivity] = []
        report = load_drift_report(self.settings)
        if report is None:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.UNAVAILABLE,
                    label="No drift report is recorded yet",
                    purpose="Reporting the current monitoring capability boundary.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.DRIFT,
                context=context,
                message=(
                    "No drift monitoring run has been recorded yet. Run the CLI with "
                    "--monitor-drift to generate a report, then ask again."
                ),
                activities=activities,
            )
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label="Loaded the latest drift monitoring report",
                purpose="Reporting which measures moved and which thresholds were crossed.",
            ),
            activities,
            listener,
        )
        material = report.material_alerts
        rows: list[list[str | int | float | None]] = [
            [
                alert.category.value,
                alert.metric_name,
                alert.breached,
                alert.investigation_required,
                alert.detail,
            ]
            for alert in report.alerts
        ]
        table = ChatTable(
            title="Drift monitoring - data, behavior, operational, and configuration alerts",
            columns=["category", "metric", "breached", "investigation_required", "detail"],
            rows=rows,
        )
        if material:
            message = (
                f"{len(material)} measure(s) crossed their threshold and require investigation: "
                + "; ".join(f"{a.metric_name} ({a.category.value})" for a in material)
                + "."
            )
        else:
            message = "No material drift was detected in the latest monitoring run."
        return ChatResponse(
            intent=ChatIntent.DRIFT,
            context=context,
            message=message,
            activities=activities,
            tables=[table],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/chat/service.py tests/test_chat_service.py
git commit -m "feat: wire the chat DRIFT intent to the real drift monitoring report"
```

---

### Task 13: Streamlit Monitoring tab

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py`
- Test: `tests/test_streamlit_chat_e2e.py`

**Interfaces:**
- Consumes: `pricing_copilot.drift.store.load_drift_report`, `pricing_copilot.drift.contracts.DriftAlertCategory`.
- Produces: a second `st.tabs()` entry, "Monitoring", rendering the persisted `DriftReport` grouped by category with thresholds/units/comparison periods visible; existing chat behavior on the "Chat" tab is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streamlit_chat_e2e.py (add to the existing file)
def test_monitoring_tab_shows_an_honest_message_with_no_drift_report_recorded() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py")
    app.run(timeout=30)
    assert app.tabs
    monitoring_tab = app.tabs[1]
    assert any(
        "no drift monitoring run" in block.value.lower()
        for block in monitoring_tab.get("info")
    )
```

Note: read the existing tests in this file first to confirm the exact `AppTest` invocation pattern (timeout, any env/settings monkeypatching already used for other Streamlit e2e tests) and follow it exactly rather than inventing a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -k monitoring_tab -v`
Expected: FAIL - there is only one tab (or no tabs at all yet).

- [ ] **Step 3: Implement**

In `src/pricing_copilot/streamlit_app.py`, add the import:

```python
from pricing_copilot.drift.contracts import DriftAlertCategory
```

Add a render function (place it near `_render_response`):

```python
def _render_drift_monitoring_tab() -> None:
    from pricing_copilot.drift.store import load_drift_report

    st.subheader("Drift and change-promotion monitoring")
    report = load_drift_report(get_settings())
    if report is None:
        st.info(
            "No drift monitoring run has been recorded yet. Run "
            "`pricing-copilot --monitor-drift` to generate one."
        )
        return
    st.caption(f"Generated {report.generated_at.isoformat()} - {report.report_version}")
    material = report.material_alerts
    if material:
        st.warning(f"{len(material)} measure(s) require investigation.", icon="⚠️")
    else:
        st.success("No material drift detected in the latest run.")
    for category in DriftAlertCategory:
        category_alerts = [alert for alert in report.alerts if alert.category is category]
        if not category_alerts:
            continue
        with st.expander(
            f"{category.value.title()} alerts ({len(category_alerts)})", expanded=bool(material)
        ):
            for alert in category_alerts:
                if alert.investigation_required:
                    status = "🔴 investigation required"
                elif alert.insufficient_sample:
                    status = "🟡 insufficient sample"
                else:
                    status = "🟢 normal"
                st.markdown(f"**{alert.metric_name}** - {status}")
                st.caption(f"Baseline: {alert.baseline_window} | Current: {alert.current_window}")
                st.write(alert.detail)
                for measurement in alert.measurements:
                    st.caption(
                        f"{measurement.measure_kind.value}: {measurement.value:g} "
                        f"{measurement.unit} (threshold {measurement.threshold:g}, "
                        f"{'breached' if measurement.breached else 'within range'})"
                    )
```

Now restructure the bottom of the file to use tabs. Replace the block from `for message_number, message in enumerate(st.session_state.chat_messages):` through the end of the file with:

```python
tab_chat, tab_monitoring = st.tabs(["Chat", "Monitoring"])

with tab_chat:
    for message_number, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(message["role"]):
            response = ChatResponse.model_validate(message["response"])
            _render_response(response, message_number, can_record=False)

    if prompt := st.chat_input(
        "Ask a portfolio-level pricing question",
        key="pricing_chat_input",
        max_chars=1_000,
        submit_mode="disable",
    ):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.chat_messages.append(
            {
                "role": "user",
                "response": ChatResponse(
                    intent=ChatIntent.HELP, context=ChatContext(), message=prompt
                ).model_dump(mode="json"),
            }
        )
        with st.chat_message("assistant"):
            activity_box = st.empty()
            activity_lines: list[str] = []

            def show_activity(activity: ChatActivity) -> None:
                activity_lines.append(_activity_text(activity))
                activity_box.markdown("  \n".join(activity_lines[-10:]))

            with st.spinner("Working with governed portfolio sources..."):
                response = ChatService().submit(prompt, on_activity=show_activity)
            activity_box.empty()
            if "Live analysis could not complete" in response.message:
                message_number = len(st.session_state.chat_messages)
                if st.button("Try replay instead", key=f"replay_retry_{message_number}"):
                    retry_context = ChatContext(
                        scenario=response.context.scenario, force_replay=True
                    )
                    response = ChatService().submit(prompt, retry_context, on_activity=show_activity)
            if response.activities:
                with st.expander("Activity trace", expanded=True):
                    st.write(
                        "\n".join(
                            f"- {_activity_text(activity)}" for activity in response.activities
                        )
                    )
            message_number = len(st.session_state.chat_messages)
            _render_response(response, message_number, can_record=True)
        st.session_state.chat_messages.append(
            {"role": "assistant", "response": response.model_dump(mode="json")}
        )

with tab_monitoring:
    _render_drift_monitoring_tab()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS (full file - confirm the existing chat tests still pass now that they run inside the "Chat" tab).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: add a Streamlit Monitoring tab for the drift report"
```

---

### Task 14: README documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Read the current README's structure**

Run: `grep -n "^## " README.md`

Find the "## Drift and release governance" heading (or similar) referenced in earlier plans, and the "## Evaluation strategy" section.

- [ ] **Step 2: Add a "Drift monitoring" subsection**

Under the drift-related heading, add a short paragraph and command block:

```markdown
### Drift monitoring

The drift monitor (`src/pricing_copilot/drift/`) compares a reproducible 25-month
"month-25" dataset (`ScenarioName.DRIFT_MONITORING`, months 1-24 stable, month 25
deliberately shifted) against its own trailing 12-month baseline, and compares the
latest golden-evaluation benchmark against configured behavior/operational floors and
ceilings (`Settings.drift`). It covers four alert categories: data (claim severity,
claim frequency, loss ratio, conversion, competitor index, feedback topics), behavior
(routing accuracy, citation coverage, safe abstention, recommendation distribution,
governance rejection, golden-suite pass rate), operational (latency, tokens, cost, tool
failures, invalid outputs), and configuration (any changed version field).

Run it after an evaluation report exists:

```bash
uv run pricing-copilot --evaluate
uv run pricing-copilot --monitor-drift
```

This writes `var/drift/latest.json`, which the chat interface's "show me drift
monitoring" and the Streamlit Monitoring tab both read.

### Change-promotion gate

`uv run pricing-copilot --check-promotion` compares the latest evaluation report's
actuals against its targets. If every required metric and every golden case passes,
the report is saved to `var/evaluation/promoted.json` as the current default; if not,
the command exits non-zero, lists every failing metric and case, and leaves the
existing `promoted.json` untouched.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document drift monitoring and the change-promotion gate"
```

---

### Task 15: Generate real artifacts, run the full quality suite, and smoke-test

**Files:**
- None created (verification and artifact-generation task).

- [ ] **Step 1: Rebuild the persistent database and generate a real evaluation report**

```bash
rm -f var/synthetic_portfolio.duckdb
uv run pricing-copilot --build-data
uv run pricing-copilot --evaluate
```

Confirm the printed summary shows the same governed pass/fail/error counts as before (the month-25 dataset must not affect the existing 18 golden cases, since none of them reference `ScenarioName.DRIFT_MONITORING`).

- [ ] **Step 2: Generate the real drift report**

```bash
uv run pricing-copilot --monitor-drift
```

Read `var/drift/latest.json` and manually verify: all six `DATA` alerts are present with `domain` set; `claim_severity`, `claim_frequency`, `loss_ratio`, `conversion`, and `competitor_index` should show `breached: true` (the month-25 dataset was deliberately engineered to trigger them); `feedback_topics` should show `breached: true` via `population_stability_index`; `BEHAVIOR`/`OPERATIONAL` alerts should show `breached: false` (the real evaluation report meets every target); exactly one `CONFIGURATION` alert with `insufficient_sample: true` (first run, no previous snapshot).

- [ ] **Step 3: Run the change-promotion gate against the real report**

```bash
uv run pricing-copilot --check-promotion
```

Expected: exit 0, `var/evaluation/promoted.json` created, message states every gate passed.

- [ ] **Step 4: Prove promotion rejection with a deliberately failing report**

```bash
uv run python -c "
from pricing_copilot.config import get_settings
from pricing_copilot.evaluation.store import load_benchmark_report, save_benchmark_report
settings = get_settings()
report = load_benchmark_report(settings)
failing = report.model_copy(
    update={'governed': report.governed.model_copy(
        update={'actuals': report.governed.actuals.model_copy(
            update={'specialist_routing_accuracy_pct': 10.0}
        )}
    )}
)
save_benchmark_report(failing, settings)
"
uv run pricing-copilot --check-promotion; echo "exit code: \$?"
```

Expected: exit code 1, stderr lists `specialist_routing_accuracy_pct` as a failing metric, `var/evaluation/promoted.json` timestamp is unchanged from Step 3 (the failed run must not overwrite it). Regenerate the real evaluation report afterward to restore `var/evaluation/latest.json`:

```bash
uv run pricing-copilot --evaluate
```

- [ ] **Step 5: Run the full quality suite**

```bash
./scripts/quality.sh
```

Expected: Ruff, MyPy strict, full pytest, Bandit, and the secret scan all pass with exit code 0. Fix anything the suite surfaces before proceeding (follow the same discipline used throughout this repository's history: investigate root causes, do not weaken checks).

- [ ] **Step 6: Manual browser smoke test**

Start the Streamlit app, ask "Show me drift monitoring" in the Chat tab and confirm the material-alerts table renders; switch to the Monitoring tab and confirm all four category expanders render with correct thresholds/units/comparison periods and the top-level warning banner. Also verify a completely fresh environment (no `var/drift/latest.json`) shows the honest "no drift monitoring run recorded yet" message in both the chat and the Monitoring tab.

- [ ] **Step 7: Secret-scan and commit the real artifacts**

```bash
grep -i -E "api[_-]?key|AZURE_OPENAI|sk-|secret|password" var/drift/latest.json var/evaluation/promoted.json
git add var/drift/latest.json var/evaluation/promoted.json var/evaluation/latest.json var/synthetic_portfolio.duckdb
git status --short
git commit -m "chore: record real drift and promotion artifacts"
```

(Only commit `var/synthetic_portfolio.duckdb` if it is already tracked in this repository - check `git ls-files var/synthetic_portfolio.duckdb` first; if it has never been committed, leave it untracked exactly as the existing `.gitignore` pattern already governs it.)

---

### Task 16: Push and close the GitHub issue

**Files:**
- None (repository/process task).

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: Close issue #11**

Use `gh issue close 11 --comment "..."` with a detailed summary covering: the month-25 dataset design and why it is a new `ScenarioName` member rather than an extension of an existing scenario; the four detectors and which statistical measure each domain uses and why (documenting the KS-test-on-competitor-index and PSI-on-feedback-topics design choices explicitly, since they are the least obvious calls in this plan); the real measured drift results from Task 15; the promotion gate and its floor/ceiling metric split; the drift-penalty hook in `calculate_confidence` and how it is demonstrated; the chat and Streamlit surfaces; and confirmation that the full quality suite passed and the demonstration requires no live Azure credentials.

---

## Self-Review Notes

**Spec coverage:**
- Six data-drift domains: Task 4 (`DriftDomain` has exactly six members, one alert each).
- PSI/KS/percentage-movement/rolling-z-score "appropriate uses": Task 4 documents the mapping explicitly (z-score+movement for the five monthly-aggregate domains, KS-test for competitor_index's genuine per-observation sample, PSI for feedback_topics' categorical share vector).
- Behavior monitoring's six required signals: Task 6 (`detect_behavior_drift`) - routing accuracy, citation coverage, safe abstention, recommendation distribution, governance rejection, golden-suite pass rate all present.
- Operational monitoring's six required signals: Task 6 (`detect_operational_drift`) - latency, tokens, cost, tool failures (via Task 5's real `tool_call_failures` fix), retries (folded into the same RETRY/FAILURE trace-event count), invalid structured outputs (`output_schema_valid_pct`).
- Configuration monitoring: Task 7, diffs every `ConfigurationVersions` field (model, prompt, agent registry, tool, dataset, policy versions are all already fields on that model).
- Versioned, reproducible month-25 dataset: Task 1 (fixed seed, deterministic).
- "Shows which measures moved, why the threshold was crossed, what investigation is required": every `DriftAlert.detail` states this; `investigation_required` is explicit.
- Material drift lowers confidence: Task 10.
- Monitoring interface separates the four categories: Task 13 (`DriftAlertCategory` iteration with one expander per category).
- Configurable thresholds with units/comparison periods: Task 3 (`DriftPolicySettings`) + Task 4's `DriftMeasurement.unit`/`comparison_period` fields.
- Baseline windows and insufficient-sample behavior explicit: Task 4's `insufficient_sample` branch, tested directly.
- Promotion gate blocking a non-passing change, recording failing cases, preserving the current default: Task 9 + Task 15 Step 4 (explicit rejection proof).
- Chat-first requirements (natural-language drift questions, launching the month-25 journey, material drift reflected in the conversational answer, discoverable from chat and the structured view): Task 12 + Task 13.
- Tests covering normal variation, threshold crossings, insufficient data, configuration changes, promotion rejection: Tasks 4, 6, 7, 9 each test both a passing and a breaching case; Task 15 Step 4 proves rejection end-to-end with a real report.
- Works in both live and replay modes: every detector operates on already-persisted data (DuckDB, a saved `BenchmarkReport`, a saved `ConfigurationVersions` snapshot) with zero live model calls - Task 15's quality suite run (no `@requires_azure_openai` marker anywhere in the new test files) is the concrete proof.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `DriftAlert`/`DriftReport`/`DriftMeasurement` field names are identical across Tasks 3-13 (`category`, `metric_name`, `domain`, `measurements`, `breached`, `investigation_required`, `confidence_impact`, `insufficient_sample`, `baseline_window`, `current_window`, `detail`). `CaseResult.action`/`tool_call_failures` (Task 5) are consumed with matching names in Task 6's behavior detector. `Settings.drift`/`Settings.drift_directory` (Task 3) are consumed identically by Tasks 4, 6, 8, 11, 12, 13.

**Known follow-on risk to flag when closing the issue:** Task 1's exact drift-trigger magnitudes (1.35x claim frequency, 1.45x severity, 1.20x competitor index, etc.) were chosen to clear the default `DriftPolicySettings` thresholds by a comfortable margin, verified in Task 15 Step 2 - if a future change lowers those thresholds, re-verify the month-25 dataset still triggers every intended alert.
