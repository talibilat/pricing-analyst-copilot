# Deliver Retention-Concern and Conflicting-Evidence Journeys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the two remaining designed scenarios (`retention_concern`, `conflicting_evidence`) through the exact same pipeline as `controlled_increase` from #3/#4/#5 - same data contracts, service boundary, interface, review controls, and decision records. Add two new deterministic safety gates the pipeline was missing: incomplete-data detection (a calculator failure must produce a safe `investigate` outcome, not a 500) and a material-evidence-issues gate (stale documents past a configured freshness policy, or same-source-type documents with directly conflicting sentiment) that also short-circuits to `investigate` before ever calling the model.

**Architecture:** `data/generation.py` gains two new scenario generators alongside the existing controlled-increase one; `documents/corpus.py` gains two new curated document sets. `workflow.py`'s `_evidence_backed_workflow_result` gains two try/gate points: a `MetricCalculationError` catch around analytics construction, and a call to a new `evidence/policy.py::detect_material_evidence_issues` after retrieval but before synthesis - both fall through to a new `_data_quality_investigation_result` helper that mirrors the existing safe-abstention shape from #2 but names the specific domain and reason. `FakeRecommendationSynthesizer` becomes data-driven (picks its canned action from the analytics it receives) so it produces sensible results across all three scenarios without per-test overrides. Governance gains a deterministic causal-language softener so no code path can describe correlational demand movement as causal, regardless of what the model outputs.

**Tech Stack:** No new dependencies.

## Global Constraints

- `retention_concern` data: stable loss ratio, material conversion/retention decline, competitor price reductions, repeated aggregate price-concern feedback, and a previous increase with a materially adverse retention/conversion outcome.
- `retention_concern` result: `hold` or a limited `decrease`, with an explicitly named elasticity investigation in `investigation_areas`.
- `conflicting_evidence` data: deteriorating claims, one stale market document (older than the configured freshness policy), incomplete conversion evidence (fewer than 24 months), and two same-source-type documents with directly conflicting sentiment.
- `conflicting_evidence` result: `investigate`, `price_range` is `None`, no implied pricing action.
- A calculator raising `MetricCalculationError` (missing/incomplete required evidence) must produce a safe `investigate` outcome through the public seam - never an unhandled 500.
- Stale evidence (older than `settings.policy.max_evidence_age_days`) forces `investigate` - a hard gate, not just a lower confidence score.
- Directly conflicting same-source-type documents force `investigate` - conflicts are surfaced, never silently averaged into a confidence penalty alone.
- No description of a demand/behavioral movement may use causal language (`caused`, `led to`, `resulted in`, `drove`, `due to`) - deterministically softened to correlational phrasing regardless of what the model produces, so this holds even against the live model.
- Aggregate customer feedback stays portfolio-level and thematic - no personal or protected attributes anywhere in the corpus (already true of the #4 corpus design; the two new document sets follow the same pattern).
- Adding these two scenarios must not change the `controlled_increase` expected result - verified by rerunning its existing tests unchanged.
- The Streamlit scenario selector already lists all three `ScenarioName` values (from #2); no UI changes are required for scenario switching itself - only the underlying data/gates need to exist.

---

## File Structure

```
src/pricing_copilot/config.py                        # MODIFY: PolicySettings.max_evidence_age_days
src/pricing_copilot/data/generation.py                # MODIFY: implement retention_concern + conflicting_evidence generators
src/pricing_copilot/documents/corpus.py               # MODIFY: add two new document sets + scenario dispatch
src/pricing_copilot/evidence/policy.py                # NEW: detect_material_evidence_issues
src/pricing_copilot/recommendation/synthesizer.py      # MODIFY: FakeRecommendationSynthesizer becomes data-driven; SYSTEM_PROMPT causal-language guidance
src/pricing_copilot/recommendation/governance.py       # MODIFY: deterministic causal-language softening
src/pricing_copilot/workflow.py                        # MODIFY: all 3 scenarios implemented; MetricCalculationError catch; material-issues gate
tests/test_data_generation.py                          # MODIFY: replace the now-invalid "unimplemented scenario" test with shape tests for both new datasets
tests/test_documents_corpus.py                         # MODIFY: same - both new scenarios now have documents
tests/test_evidence_policy.py                          # NEW
tests/test_recommendation_governance.py                # MODIFY: add causal-language softening tests
tests/test_workflow.py                                 # MODIFY: add retention_concern and conflicting_evidence e2e tests; confirm controlled_increase unchanged
tests/test_api.py                                       # MODIFY: e2e tests for both new scenarios through the API
tests/test_recommendation_live.py                       # MODIFY: add a live retention_concern test (gated on credentials) and an unconditional conflicting_evidence test (never touches the model, so no credential gate needed)
```

**Interfaces summary:**
- `data/generation.py`: `generate_scenario_dataset` now handles all three `ScenarioName` values; `NotImplementedError` fallback stays as a defensive default for any future enum addition.
- `documents/corpus.py`: `documents_for_scenario` dispatches via a `dict[ScenarioName, list[DocumentRecord]]` instead of a single `if`.
- `evidence/policy.py` exports: `detect_material_evidence_issues(documents, *, analysis_period_end, max_evidence_age_days) -> list[str]`.
- `config.py`: `PolicySettings.max_evidence_age_days: int = 120`.
- `recommendation/governance.py` exports: `GOVERNANCE_VERSION` (unchanged) plus the softening applied inside `validate_and_clamp_draft` (no new public function).
- `workflow.py` gains: `_data_quality_investigation_result(question, reason) -> WorkflowResult` (private helper).

---

## Task 1: Policy setting for evidence freshness

**Files:** Modify `src/pricing_copilot/config.py`.

- [ ] **Step 1: Add the setting**

```python
class PolicySettings(BaseModel):
    max_price_movement_pct: float = 5.0
    max_evidence_age_days: int = 120
```

- [ ] **Step 2: Verify**

Run: `uv run python -c "from pricing_copilot.config import Settings; print(Settings().policy.max_evidence_age_days)"`
Expected: `120`

- [ ] **Step 3: Commit**

```bash
git add src/pricing_copilot/config.py
git commit -m "chore: add configurable evidence freshness policy"
```

---

## Task 2: Material evidence issues gate

**Files:** Create `src/pricing_copilot/evidence/policy.py`; Test: `tests/test_evidence_policy.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evidence_policy.py
from datetime import date

from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.evidence.policy import detect_material_evidence_issues


def _document(
    document_id: str,
    source_type: SourceType,
    sentiment: DocumentSentiment,
    source_date: date,
) -> RetrievedDocument:
    return RetrievedDocument(
        document=DocumentRecord(
            document_id=document_id,
            source_type=source_type,
            title="t",
            body="b",
            source_date=source_date,
            scenario=ScenarioName.CONFLICTING_EVIDENCE,
            region=Region.NORTH_WEST,
            sentiment=sentiment,
        ),
        score=1.0,
    )


def test_no_issues_for_fresh_consistent_documents() -> None:
    documents = [
        _document("d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 12, 1)),
        _document("d2", SourceType.BROKER_NOTE, DocumentSentiment.NEUTRAL, date(2025, 11, 15)),
    ]
    assert detect_material_evidence_issues(
        documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    ) == []


def test_stale_document_is_flagged() -> None:
    documents = [
        _document("d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 1, 1)),
    ]
    issues = detect_material_evidence_issues(
        documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    )
    assert len(issues) == 1
    assert "d1" in issues[0]
    assert "market_intelligence" in issues[0]


def test_conflicting_same_type_documents_are_flagged() -> None:
    documents = [
        _document("d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 12, 1)),
        _document("d2", SourceType.MARKET_REPORT, DocumentSentiment.AGAINST_INCREASE, date(2025, 12, 1)),
    ]
    issues = detect_material_evidence_issues(
        documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    )
    assert len(issues) == 1
    assert "conflicting" in issues[0]


def test_conflicting_different_type_documents_are_not_flagged() -> None:
    documents = [
        _document("d1", SourceType.MARKET_REPORT, DocumentSentiment.SUPPORTS_INCREASE, date(2025, 12, 1)),
        _document("d2", SourceType.CUSTOMER_FEEDBACK, DocumentSentiment.AGAINST_INCREASE, date(2025, 12, 1)),
    ]
    assert detect_material_evidence_issues(
        documents, analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    ) == []


def test_no_documents_has_no_issues() -> None:
    assert detect_material_evidence_issues(
        [], analysis_period_end=date(2025, 12, 15), max_evidence_age_days=120
    ) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_evidence_policy.py -v`
Expected: `ModuleNotFoundError: No module named 'pricing_copilot.evidence.policy'`

- [ ] **Step 3: Implement**

```python
# src/pricing_copilot/evidence/policy.py
from __future__ import annotations

from datetime import date

from pricing_copilot.documents.corpus import DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument

_CONFLICTING_PAIR = {DocumentSentiment.SUPPORTS_INCREASE, DocumentSentiment.AGAINST_INCREASE}


def detect_material_evidence_issues(
    documents: list[RetrievedDocument],
    *,
    analysis_period_end: date,
    max_evidence_age_days: int,
) -> list[str]:
    issues: list[str] = []

    stale = [
        retrieved
        for retrieved in documents
        if (analysis_period_end - retrieved.document.source_date).days > max_evidence_age_days
    ]
    if stale:
        stale_ids = ", ".join(retrieved.document.document_id for retrieved in stale)
        issues.append(
            f"market_intelligence: {len(stale)} retrieved document(s) exceed the "
            f"{max_evidence_age_days}-day evidence freshness policy ({stale_ids})."
        )

    sentiments_by_type: dict[SourceType, set[DocumentSentiment]] = {}
    for retrieved in documents:
        sentiments_by_type.setdefault(retrieved.document.source_type, set()).add(
            retrieved.document.sentiment
        )
    conflicting_types = [
        source_type.value
        for source_type, sentiments in sentiments_by_type.items()
        if _CONFLICTING_PAIR <= sentiments
    ]
    if conflicting_types:
        issues.append(
            "market_intelligence: materially conflicting "
            f"{', '.join(conflicting_types)} documents disagree on market direction and "
            "cannot be silently averaged away."
        )

    return issues
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_evidence_policy.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/evidence/policy.py tests/test_evidence_policy.py
git commit -m "feat: add material evidence issues gate (staleness + conflict detection)"
```

---

## Task 3: Retention-concern and conflicting-evidence data generators

**Files:** Modify `src/pricing_copilot/data/generation.py`, `tests/test_data_generation.py`.

- [ ] **Step 1: Update the failing/changed tests**

In `tests/test_data_generation.py`, replace `test_unimplemented_scenario_raises_not_implemented` (its premise - an unimplemented scenario existing - is no longer true) with:

```python
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
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/test_data_generation.py -v`
Expected: `test_retention_concern_dataset_has_24_monthly_periods_per_domain` and `test_conflicting_evidence_dataset_has_incomplete_conversion_data` FAIL with `NotImplementedError`; existing controlled-increase tests still PASS.

- [ ] **Step 3: Implement the retention-concern generator**

Add to `src/pricing_copilot/data/generation.py` (after `_generate_controlled_increase_dataset`):

```python
def _generate_retention_concern_claims(
    rng: random.Random, periods: list[date]
) -> list[ClaimsMonthlyRecord]:
    records = []
    for period in periods:
        policies = round(_jitter(rng, 5000, 0.01))
        claim_count = round(_jitter(rng, 420, 0.03))
        severity = _jitter(rng, 1606.0, 0.02)  # stable target across both windows
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


def _generate_retention_concern_conversion(
    rng: random.Random, periods: list[date]
) -> list[ConversionMonthlyRecord]:
    records = []
    # (segment, baseline_conversion, current_conversion, baseline_retention, current_retention)
    segment_config: tuple[tuple[Segment, float, float, float | None, float | None], ...] = (
        (Segment.RENEWAL, 0.22, 0.19, 0.88, 0.74),
        (Segment.NEW_BUSINESS, 0.15, 0.15, None, None),
    )
    for segment, base_conv, current_conv, base_ret, current_ret in segment_config:
        for index, period in enumerate(periods):
            is_current = index >= 12
            conv_target = current_conv if is_current else base_conv
            quotes = round(_jitter(rng, 10_000, 0.02))
            sales = round(quotes * _jitter(rng, conv_target, 0.03))
            if base_ret is not None and current_ret is not None:
                ret_target = current_ret if is_current else base_ret
                renewals_due = round(_jitter(rng, 4_000, 0.02))
                renewals_retained = round(renewals_due * _jitter(rng, ret_target, 0.02))
            else:
                renewals_due = 0
                renewals_retained = 0
            premium = round(_jitter(rng, 620.0, 0.01), 2)
            records.append(
                ConversionMonthlyRecord(
                    period=period,
                    product=Product.PERSONAL_MOTOR,
                    region=Region.NORTH_WEST,
                    segment=segment,
                    quotes=quotes,
                    sales=sales,
                    renewals_due=renewals_due,
                    renewals_retained=renewals_retained,
                    average_quoted_premium_gbp=premium,
                )
            )
    return records


def _generate_retention_concern_competitors(
    rng: random.Random, periods: list[date]
) -> list[CompetitorMonthlyRecord]:
    records = []
    for name, base_index in COMPETITOR_BASE_INDEX.items():
        for index, period in enumerate(periods):
            is_current = index >= 12
            target = base_index * (0.95 if is_current else 1.0)
            records.append(
                CompetitorMonthlyRecord(
                    period=period,
                    region=Region.NORTH_WEST,
                    competitor_name=name,
                    price_index=round(_jitter(rng, target, 0.01), 2),
                )
            )
    return records


def _generate_retention_concern_pricing_history(periods: list[date]) -> list[PricingActionRecord]:
    return [
        PricingActionRecord(
            period=periods[5],
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            price_change_pct=2.0,
            rationale=(
                "Portfolio-level 2% renewal price increase applied earlier this year; retention "
                "softened materially in the months that followed."
            ),
            conversion_impact_pct=-8.0,
            loss_ratio_impact_pct=-0.5,
        )
    ]


def _generate_retention_concern_dataset(seed: int, version: str) -> ScenarioDataset:
    rng = random.Random(seed)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, TOTAL_MONTHS)
    return ScenarioDataset(
        scenario=ScenarioName.RETENTION_CONCERN,
        seed=seed,
        version=version,
        claims=_generate_retention_concern_claims(rng, periods),
        conversion=_generate_retention_concern_conversion(rng, periods),
        competitors=_generate_retention_concern_competitors(rng, periods),
        pricing_history=_generate_retention_concern_pricing_history(periods),
    )
```

- [ ] **Step 4: Implement the conflicting-evidence generator**

```python
CONFLICTING_EVIDENCE_CONVERSION_MONTHS = 20


def _generate_conflicting_evidence_claims(
    rng: random.Random, periods: list[date]
) -> list[ClaimsMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_current = index >= 12
        policies = round(_jitter(rng, 5000, 0.01))
        claim_count = round(_jitter(rng, 420, 0.03))
        severity_target = 1606.0 * 1.30 if is_current else 1606.0
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


def _generate_conflicting_evidence_conversion(
    rng: random.Random, periods: list[date]
) -> list[ConversionMonthlyRecord]:
    incomplete_periods = periods[:CONFLICTING_EVIDENCE_CONVERSION_MONTHS]
    records = []
    for segment, base_conversion, base_retention in (
        (Segment.RENEWAL, 0.20, 0.85),
        (Segment.NEW_BUSINESS, 0.14, None),
    ):
        for period in incomplete_periods:
            quotes = round(_jitter(rng, 10_000, 0.02))
            sales = round(quotes * _jitter(rng, base_conversion, 0.03))
            if base_retention is not None:
                renewals_due = round(_jitter(rng, 4_000, 0.02))
                renewals_retained = round(renewals_due * _jitter(rng, base_retention, 0.02))
            else:
                renewals_due = 0
                renewals_retained = 0
            premium = round(_jitter(rng, 620.0, 0.01), 2)
            records.append(
                ConversionMonthlyRecord(
                    period=period,
                    product=Product.PERSONAL_MOTOR,
                    region=Region.NORTH_WEST,
                    segment=segment,
                    quotes=quotes,
                    sales=sales,
                    renewals_due=renewals_due,
                    renewals_retained=renewals_retained,
                    average_quoted_premium_gbp=premium,
                )
            )
    return records


def _generate_conflicting_evidence_competitors(
    rng: random.Random, periods: list[date]
) -> list[CompetitorMonthlyRecord]:
    records = []
    for name, base_index in COMPETITOR_BASE_INDEX.items():
        for index, period in enumerate(periods):
            is_current = index >= 12
            target = base_index * (1.01 if is_current else 1.0)
            records.append(
                CompetitorMonthlyRecord(
                    period=period,
                    region=Region.NORTH_WEST,
                    competitor_name=name,
                    price_index=round(_jitter(rng, target, 0.01), 2),
                )
            )
    return records


def _generate_conflicting_evidence_pricing_history(periods: list[date]) -> list[PricingActionRecord]:
    return [
        PricingActionRecord(
            period=periods[5],
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            price_change_pct=1.5,
            rationale=(
                "Small portfolio-level adjustment applied earlier this year; outcome data is "
                "inconclusive given gaps in the tracking period."
            ),
            conversion_impact_pct=-1.0,
            loss_ratio_impact_pct=0.0,
        )
    ]


def _generate_conflicting_evidence_dataset(seed: int, version: str) -> ScenarioDataset:
    rng = random.Random(seed)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, TOTAL_MONTHS)
    return ScenarioDataset(
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
        seed=seed,
        version=version,
        claims=_generate_conflicting_evidence_claims(rng, periods),
        conversion=_generate_conflicting_evidence_conversion(rng, periods),
        competitors=_generate_conflicting_evidence_competitors(rng, periods),
        pricing_history=_generate_conflicting_evidence_pricing_history(periods),
    )
```

- [ ] **Step 5: Update the dispatcher**

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
    raise NotImplementedError(f"No generator implemented yet for scenario '{scenario.value}'.")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_data_generation.py -v`
Expected: PASS (all tests, including the existing controlled-increase ones - unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/pricing_copilot/data/generation.py tests/test_data_generation.py
git commit -m "feat: implement retention-concern and conflicting-evidence data generators"
```

---

## Task 4: Retention-concern and conflicting-evidence document corpora

**Files:** Modify `src/pricing_copilot/documents/corpus.py`, `tests/test_documents_corpus.py`.

- [ ] **Step 1: Update the failing/changed tests**

In `tests/test_documents_corpus.py`, replace `test_unimplemented_scenario_has_no_documents` with:

```python
def test_retention_concern_corpus_has_documents_all_against_increase_or_neutral() -> None:
    documents = documents_for_scenario(ScenarioName.RETENTION_CONCERN, Region.NORTH_WEST)
    assert documents
    assert all(
        d.sentiment in (DocumentSentiment.AGAINST_INCREASE, DocumentSentiment.NEUTRAL)
        for d in documents
    )
    feedback_docs = [d for d in documents if d.source_type == SourceType.CUSTOMER_FEEDBACK]
    assert len(feedback_docs) >= 2


def test_conflicting_evidence_corpus_has_two_conflicting_market_reports() -> None:
    documents = documents_for_scenario(ScenarioName.CONFLICTING_EVIDENCE, Region.NORTH_WEST)
    market_reports = [d for d in documents if d.source_type == SourceType.MARKET_REPORT]
    sentiments = {d.sentiment for d in market_reports}
    assert DocumentSentiment.SUPPORTS_INCREASE in sentiments
    assert DocumentSentiment.AGAINST_INCREASE in sentiments


def test_conflicting_evidence_corpus_has_a_stale_document() -> None:
    from datetime import date

    documents = documents_for_scenario(ScenarioName.CONFLICTING_EVIDENCE, Region.NORTH_WEST)
    assert any((date(2025, 12, 15) - d.source_date).days > 120 for d in documents)
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/test_documents_corpus.py -v`

- [ ] **Step 3: Add the two document sets**

Add to `src/pricing_copilot/documents/corpus.py` (after `CONTROLLED_INCREASE_DOCUMENTS`):

```python
RETENTION_CONCERN_DOCUMENTS: list[DocumentRecord] = [
    DocumentRecord(
        document_id="doc-market-retention",
        source_type=SourceType.MARKET_REPORT,
        title="North West Personal Motor Market Pulse - Retention Watch",
        body=(
            "Fictional competitor observations for illustrative purposes only. Meridian Insure, "
            "Northgate Cover, and Bracken Mutual have each reduced personal motor renewal "
            "pricing by roughly four to six percent over the past quarter, softening the "
            "competitive backdrop for any further increase."
        ),
        source_date=date(2025, 11, 20),
        scenario=ScenarioName.RETENTION_CONCERN,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.AGAINST_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-feedback-retention-1",
        source_type=SourceType.CUSTOMER_FEEDBACK,
        title="Aggregate North West Renewal Feedback Themes - November 2025",
        body=(
            "Aggregate, anonymised theme summary only. Price is now the most frequently "
            "referenced theme in renewal feedback this period, a repeated pattern rather than "
            "an isolated comment."
        ),
        source_date=date(2025, 11, 10),
        scenario=ScenarioName.RETENTION_CONCERN,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.AGAINST_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-feedback-retention-2",
        source_type=SourceType.CUSTOMER_FEEDBACK,
        title="Aggregate North West Renewal Feedback Themes - December 2025",
        body=(
            "Aggregate, anonymised theme summary only. Consistent with November: price-related "
            "comments remain the dominant theme, repeated across renewal cycles rather than "
            "concentrated in a single month."
        ),
        source_date=date(2025, 12, 1),
        scenario=ScenarioName.RETENTION_CONCERN,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.AGAINST_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-broker-retention",
        source_type=SourceType.BROKER_NOTE,
        title="Broker Panel Observations - Retention Risk",
        body=(
            "Broker panel note (synthetic). Panel members report a noticeable rise in renewal "
            "shopping-around behaviour following the previous portfolio-level increase, with "
            "several brokers flagging retention risk if pricing firms further."
        ),
        source_date=date(2025, 12, 5),
        scenario=ScenarioName.RETENTION_CONCERN,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.AGAINST_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-repair-cost-retention",
        source_type=SourceType.REPAIR_COST_REPORT,
        title="Synthetic UK Vehicle Repair Cost Index - Retention Period",
        body=(
            "Illustrative repair-cost intelligence. Cost trends this period are broadly in line "
            "with historical norms, without a clear signal in either direction for claims "
            "severity."
        ),
        source_date=date(2025, 11, 1),
        scenario=ScenarioName.RETENTION_CONCERN,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.NEUTRAL,
    ),
]

CONFLICTING_EVIDENCE_DOCUMENTS: list[DocumentRecord] = [
    DocumentRecord(
        document_id="doc-market-conflict-stale",
        source_type=SourceType.MARKET_REPORT,
        title="North West Market Briefing - Prior Quarter Snapshot",
        body=(
            "Fictional market briefing, illustrative only. As of this (now dated) snapshot, "
            "fictional competitors were continuing to raise personal motor pricing, suggesting "
            "room for further portfolio-level increases."
        ),
        source_date=date(2025, 3, 1),
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.SUPPORTS_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-market-conflict-fresh",
        source_type=SourceType.MARKET_REPORT,
        title="North West Market Briefing - Latest Repricing Signal",
        body=(
            "Fictional market briefing, illustrative only. The latest signal directly "
            "contradicts the prior-quarter snapshot: fictional competitors have sharply cut "
            "personal motor pricing in response to a softening market."
        ),
        source_date=date(2025, 12, 5),
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.AGAINST_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-repair-cost-conflict",
        source_type=SourceType.REPAIR_COST_REPORT,
        title="Synthetic UK Vehicle Repair Cost Index - Deterioration Signal",
        body=(
            "Illustrative repair-cost intelligence. Parts and labour costs have risen sharply "
            "this period, consistent with the observed deterioration in claims severity."
        ),
        source_date=date(2025, 11, 25),
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.SUPPORTS_INCREASE,
    ),
    DocumentRecord(
        document_id="doc-feedback-conflict",
        source_type=SourceType.CUSTOMER_FEEDBACK,
        title="Aggregate North West Renewal Feedback Themes - Sparse Period",
        body=(
            "Aggregate, anonymised theme summary only. Feedback volume was noticeably lower "
            "than usual this period, limiting how much weight this theme summary can carry."
        ),
        source_date=date(2025, 12, 1),
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
        region=Region.NORTH_WEST,
        sentiment=DocumentSentiment.NEUTRAL,
    ),
]
```

- [ ] **Step 4: Update the dispatch function**

Replace `documents_for_scenario`:
```python
_SCENARIO_DOCUMENTS: dict[ScenarioName, list[DocumentRecord]] = {
    ScenarioName.CONTROLLED_INCREASE: CONTROLLED_INCREASE_DOCUMENTS,
    ScenarioName.RETENTION_CONCERN: RETENTION_CONCERN_DOCUMENTS,
    ScenarioName.CONFLICTING_EVIDENCE: CONFLICTING_EVIDENCE_DOCUMENTS,
}


def documents_for_scenario(scenario: ScenarioName, region: Region) -> list[DocumentRecord]:
    corpus = _SCENARIO_DOCUMENTS.get(scenario, [])
    return [d for d in corpus if d.region == region]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_documents_corpus.py -v`
Expected: PASS (all tests, including unchanged controlled-increase ones).

- [ ] **Step 6: Commit**

```bash
git add src/pricing_copilot/documents/corpus.py tests/test_documents_corpus.py
git commit -m "feat: add retention-concern and conflicting-evidence document corpora"
```

---

## Task 5: Deterministic causal-language softening

**Files:** Modify `src/pricing_copilot/recommendation/governance.py`, `src/pricing_copilot/recommendation/synthesizer.py`; Test: `tests/test_recommendation_governance.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_recommendation_governance.py`:
```python
def test_causal_language_is_softened_to_correlational() -> None:
    draft = RecommendationDraft(
        action=RecommendationAction.HOLD,
        price_range=None,
        rationale="The price increase caused conversion to fall, which led to lower retention.",
        counter_evidence=["Higher pricing due to claims inflation resulted in demand pressure."],
        cited_evidence_ids=["claims-north_west-2025-12-01"],
    )
    validated = validate_and_clamp_draft(draft, ledger=_ledger(), max_movement_pct=5.0)
    combined = validated.rationale + " ".join(validated.counter_evidence)
    for banned in ("caused", "led to", "resulted in", "due to"):
        assert banned not in combined.lower()
    assert "coincided with" in validated.rationale.lower() or "associated with" in validated.rationale.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_recommendation_governance.py -v`
Expected: the new test FAILS (causal phrases still present, unmodified).

- [ ] **Step 3: Implement the softener**

In `src/pricing_copilot/recommendation/governance.py`, add (after `_TOLERANCE`):
```python
_CAUSAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bcaused\b", "coincided with"),
    (r"\bcauses\b", "coincides with"),
    (r"\bcausing\b", "coinciding with"),
    (r"\bled to\b", "was associated with"),
    (r"\bleads to\b", "is associated with"),
    (r"\bresulted in\b", "was followed by"),
    (r"\bresults in\b", "is followed by"),
    (r"\bdrove\b", "coincided with"),
    (r"\bdrives\b", "coincides with"),
    (r"\bdue to\b", "alongside"),
)


def _soften_causal_language(text: str) -> str:
    softened = text
    for pattern, replacement in _CAUSAL_REPLACEMENTS:
        softened = re.sub(pattern, replacement, softened, flags=re.IGNORECASE)
    return softened
```

Update the end of `validate_and_clamp_draft` (replace the final `return` statement):
```python
    return draft.model_copy(
        update={
            "price_range": price_range,
            "conditions": conditions,
            "rationale": _soften_causal_language(draft.rationale),
            "counter_evidence": [_soften_causal_language(t) for t in draft.counter_evidence],
            "investigation_areas": [_soften_causal_language(t) for t in draft.investigation_areas],
        }
    )
```

- [ ] **Step 4: Add system-prompt guidance**

In `src/pricing_copilot/recommendation/synthesizer.py`, extend `SYSTEM_PROMPT` (insert before the closing JSON-shape instruction sentence):
```python
    "Describe demand or behavioral movements (conversion, retention) using correlational "
    "language only (for example 'coincided with', 'was associated with') - never causal "
    "language (for example 'caused', 'led to', 'resulted in', 'drove') - since no causal "
    "inference method is implemented in this prototype. "
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_recommendation_governance.py -v`
Expected: PASS (all tests, including the new one and the existing ones - the softener never changes a draft with no causal language, verified implicitly by the other passing tests).

- [ ] **Step 6: Commit**

```bash
git add src/pricing_copilot/recommendation/governance.py src/pricing_copilot/recommendation/synthesizer.py tests/test_recommendation_governance.py
git commit -m "feat: deterministically soften causal language to correlational phrasing"
```

---

## Task 6: Data-driven fake synthesizer

**Files:** Modify `src/pricing_copilot/recommendation/synthesizer.py`; Test: `tests/test_recommendation_synthesizer.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_recommendation_synthesizer.py`:
```python
def test_fake_synthesizer_recommends_hold_when_retention_declines_and_loss_ratio_is_stable() -> None:
    repo = PortfolioDataRepository.from_scenario(ScenarioName.RETENTION_CONCERN)
    claims = calculate_claims_metrics(
        repo.fetch_claims(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    )
    conversion = calculate_conversion_metrics(
        repo.fetch_conversion(Product.PERSONAL_MOTOR, Region.NORTH_WEST), Segment.RENEWAL
    )
    competitors = calculate_competitor_metrics(repo.fetch_competitors(Region.NORTH_WEST))
    pricing_history = summarize_pricing_history(
        repo.fetch_pricing_history(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    )
    analytics = PortfolioAnalytics(
        claims=claims, conversion=conversion, competitors=competitors, pricing_history=pricing_history
    )
    documents = retrieve_documents(
        scenario=ScenarioName.RETENTION_CONCERN, region=Region.NORTH_WEST, query="retention conversion", top_k=5
    )
    ledger = build_evidence_ledger(
        analytics=analytics, documents=documents, region=Region.NORTH_WEST, retrieved_at=datetime.now(UTC)
    )

    draft = FakeRecommendationSynthesizer().synthesize(
        analytics=analytics, ledger=ledger, documents=documents, max_movement_pct=5.0
    )

    assert draft.action is RecommendationAction.HOLD
    assert draft.price_range is None
    assert any("elasticity" in area.lower() for area in draft.investigation_areas)
```
Add the necessary imports (`ScenarioName`, `RecommendationAction`, `datetime`, `UTC`, calculators, `PortfolioAnalytics`, `retrieve_documents`, `build_evidence_ledger`) to the top of the file alongside the existing ones.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_recommendation_synthesizer.py -v`
Expected: FAILS - the fake always returns `INCREASE` today, regardless of input.

- [ ] **Step 3: Make `FakeRecommendationSynthesizer` data-driven**

Replace its `synthesize` method body in `src/pricing_copilot/recommendation/synthesizer.py`:
```python
    def synthesize(
        self,
        *,
        analytics: PortfolioAnalytics,
        ledger: EvidenceLedger,
        documents: list[RetrievedDocument],
        max_movement_pct: float,
    ) -> RecommendationDraft:
        if self._draft is not None:
            return self._draft

        structured_ids = [e.evidence_id for e in ledger.entries if e.source_type == "structured_metric"]
        document_ids = [e.evidence_id for e in ledger.entries if e.source_type != "structured_metric"]
        cited = (structured_ids + document_ids)[:4]

        loss_ratio_movement = analytics.claims.loss_ratio.movement_pct or 0.0
        retention_movement = analytics.conversion.renewal_retention.movement_pct or 0.0

        if retention_movement < -5.0 and loss_ratio_movement < 5.0:
            return RecommendationDraft(
                action=RecommendationAction.HOLD,
                price_range=None,
                rationale=(
                    "Renewal retention has softened materially while the loss ratio remains "
                    "broadly stable, so no increase is supported at this time."
                ),
                counter_evidence=[
                    "Loss ratio has not deteriorated, so cost pressure alone does not justify "
                    "any reduction either."
                ],
                conditions=[],
                investigation_areas=[
                    "Run a price elasticity investigation for the affected segment before any "
                    "further pricing action."
                ],
                cited_evidence_ids=cited,
            )

        return RecommendationDraft(
            action=RecommendationAction.INCREASE,
            price_range=PriceRange(lower_pct=2.0, upper_pct=3.0),
            rationale=(
                "Claim severity and loss ratio have risen while competitor pricing has firmed "
                "and conversion has remained resilient, supporting a controlled pilot increase."
            ),
            counter_evidence=[
                "Quote-to-sale conversion has moved only slightly, limiting evidence of "
                "pricing headroom."
            ],
            conditions=["Limit rollout to a pilot cohort before full portfolio adoption."],
            investigation_areas=["Confirm repair-cost inflation persists into next quarter."],
            cited_evidence_ids=cited,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recommendation_synthesizer.py -v`
Expected: PASS (both the existing controlled-increase test and the new retention-concern test).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/recommendation/synthesizer.py tests/test_recommendation_synthesizer.py
git commit -m "feat: make FakeRecommendationSynthesizer data-driven across scenarios"
```

---

## Task 7: Wire both scenarios and the safety gates into the workflow

**Files:** Modify `src/pricing_copilot/workflow.py`, `tests/test_workflow.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_workflow.py` (with the necessary new imports: `RecommendationDraft` is already imported; add `PriceRange` if not present - it already is from the #4 test):
```python
def test_retention_concern_scenario_recommends_hold_with_elasticity_investigation() -> None:
    question = _question().model_copy(update={"scenario": ScenarioName.RETENTION_CONCERN})

    result = run_portfolio_workflow(question, synthesizer=FakeRecommendationSynthesizer())

    assert result.missing_evidence == []
    assert result.recommendation.action in (RecommendationAction.HOLD, RecommendationAction.DECREASE)
    assert result.recommendation.price_range is None or (
        result.recommendation.price_range.upper_pct <= 0
    )
    assert any(
        "elasticity" in area.lower() for area in result.recommendation.investigation_areas
    )
    assert result.analytics is not None
    retention_movement = result.analytics.conversion.renewal_retention.movement_pct
    assert retention_movement is not None and retention_movement < -5.0


def test_conflicting_evidence_scenario_forces_investigate_without_calling_the_model() -> None:
    question = _question().model_copy(update={"scenario": ScenarioName.CONFLICTING_EVIDENCE})

    # No synthesizer is passed - if this reaches synthesis it would try the real Azure
    # OpenAI-backed default, which would fail fast in an environment without network access.
    # The material-evidence-issues gate must short-circuit before that ever happens.
    result = run_portfolio_workflow(question)

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.recommendation.price_range is None
    assert result.missing_evidence
    assert result.missing_evidence[0].domain is EvidenceDomain.CONVERSION or (
        result.missing_evidence[0].domain is EvidenceDomain.MARKET_INTELLIGENCE
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: both new tests FAIL - `RETENTION_CONCERN`/`CONFLICTING_EVIDENCE` are not yet in `IMPLEMENTED_DATA_SCENARIOS`, so they currently hit the plain missing-evidence path (which would actually make the retention-concern test fail on `result.recommendation.action` and the conflicting-evidence test would pass by accident for the wrong reason - inspect the actual failure before proceeding).

- [ ] **Step 3: Rewrite the relevant parts of `workflow.py`**

Add imports:
```python
from pricing_copilot.analytics.calculators import (
    MetricCalculationError,
    calculate_claims_metrics,
    calculate_competitor_metrics,
    calculate_conversion_metrics,
    summarize_pricing_history,
)
from pricing_copilot.evidence.policy import detect_material_evidence_issues
```
(add `MetricCalculationError` to the existing `analytics.calculators` import line; add the new `evidence.policy` import near the other `evidence.*` imports)

Update `IMPLEMENTED_DATA_SCENARIOS`:
```python
IMPLEMENTED_DATA_SCENARIOS: frozenset[ScenarioName] = frozenset(
    {ScenarioName.CONTROLLED_INCREASE, ScenarioName.RETENTION_CONCERN, ScenarioName.CONFLICTING_EVIDENCE}
)
```

Add a domain-detection helper and the investigate-fallback result builder (after `_missing_evidence_workflow_result`):
```python
_DOMAIN_ERROR_PREFIXES: dict[str, EvidenceDomain] = {
    "claims": EvidenceDomain.CLAIMS,
    "conversion": EvidenceDomain.CONVERSION,
    "competitors": EvidenceDomain.MARKET_INTELLIGENCE,
    "market_intelligence": EvidenceDomain.MARKET_INTELLIGENCE,
    "pricing_history": EvidenceDomain.PRICING_HISTORY,
}


def _domain_from_error_message(message: str) -> EvidenceDomain:
    prefix = message.split(":", 1)[0].strip()
    for key, domain in _DOMAIN_ERROR_PREFIXES.items():
        if prefix.startswith(key):
            return domain
    return EvidenceDomain.CLAIMS


def _data_quality_investigation_result(question: PortfolioQuestion, reason: str) -> WorkflowResult:
    domain = _domain_from_error_message(reason)
    missing_evidence = [MissingEvidence(domain=domain, reason=reason)]
    specialist_reports = [
        SpecialistReport(
            domain=domain,
            status="error",
            evidence_ids=[],
            summary=reason,
            missing_evidence=missing_evidence,
        )
    ]
    recommendation = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        rationale=(
            f"Investigation is required: {reason} This gap is material enough that no "
            "pricing claim can be safely supported for this period."
        ),
    )
    governance_outcome = GovernanceOutcome(
        approved=True,
        reasons=[
            "An investigate outcome proposes no price movement and cites no unsupported claims."
        ],
    )
    return WorkflowResult(
        question=question,
        specialist_reports=specialist_reports,
        recommendation=recommendation,
        governance_outcome=governance_outcome,
        missing_evidence=missing_evidence,
    )
```

Update `_evidence_backed_workflow_result` to wrap analytics construction and add the material-issues gate:
```python
def _evidence_backed_workflow_result(
    question: PortfolioQuestion, settings: Settings, synthesizer: RecommendationSynthesizer | None
) -> WorkflowResult:
    scenario = question.scenario
    if scenario is None:
        raise ValueError("Evidence-backed workflow requires a scenario.")

    repository = PortfolioDataRepository.from_scenario(scenario)

    try:
        analytics = _build_analytics(question, repository)
    except MetricCalculationError as exc:
        return _data_quality_investigation_result(question, str(exc))

    retrieved_documents = retrieve_documents(
        scenario=scenario, region=question.region, query=RETRIEVAL_QUERY, top_k=6
    )

    material_issues = detect_material_evidence_issues(
        retrieved_documents,
        analysis_period_end=analytics.claims.period_end,
        max_evidence_age_days=settings.policy.max_evidence_age_days,
    )
    if material_issues:
        return _data_quality_investigation_result(question, "; ".join(material_issues))

    retrieved_at = datetime.now(UTC)
    ledger = build_evidence_ledger(
        analytics=analytics,
        documents=retrieved_documents,
        region=question.region,
        retrieved_at=retrieved_at,
    )

    active_synthesizer = synthesizer or get_default_synthesizer(settings)
    draft = active_synthesizer.synthesize(
        analytics=analytics,
        ledger=ledger,
        documents=retrieved_documents,
        max_movement_pct=settings.policy.max_price_movement_pct,
    )
    validated = validate_and_clamp_draft(
        draft, ledger=ledger, max_movement_pct=settings.policy.max_price_movement_pct
    )

    confidence = calculate_confidence(
        ledger=ledger,
        documents=retrieved_documents,
        analytics=analytics,
        action=validated.action,
        analysis_period_end=analytics.claims.period_end,
    )
    fair_value_status, fair_value_follow_up = calculate_fair_value_status(
        action=validated.action,
        conversion_movement_pct=analytics.conversion.quote_to_sale_conversion.movement_pct,
        documents=retrieved_documents,
    )

    recommendation = Recommendation(
        action=validated.action,
        price_range=validated.price_range,
        rationale=validated.rationale,
        counter_evidence=validated.counter_evidence,
        conditions=validated.conditions,
        investigation_areas=validated.investigation_areas,
        cited_evidence_ids=validated.cited_evidence_ids,
        confidence=confidence,
        fair_value_status=fair_value_status,
        fair_value_follow_up=fair_value_follow_up,
    )

    governance_outcome = GovernanceOutcome(
        approved=True,
        reasons=[
            "Recommendation validated: all cited evidence ids exist in the ledger and the "
            "proposed range is within the configured policy limit."
        ],
    )

    return WorkflowResult(
        question=question,
        specialist_reports=_specialist_reports(question, analytics, len(retrieved_documents)),
        recommendation=recommendation,
        governance_outcome=governance_outcome,
        missing_evidence=[],
        analytics=analytics,
        evidence_ledger=ledger,
    )
```

This is the same function as before with two additions: the `try/except MetricCalculationError` around `_build_analytics`, and the `material_issues` gate placed after retrieval but before ledger construction and synthesis - so `conflicting_evidence` (which fails via the `MetricCalculationError` path given its incomplete conversion data) never reaches `get_default_synthesizer`, and by construction needs no model credentials to test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: PASS (all tests, including the two new ones and the existing controlled-increase ones unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/workflow.py tests/test_workflow.py
git commit -m "feat: wire retention-concern and conflicting-evidence scenarios with safety gates"
```

---

## Task 8: API e2e coverage for both new scenarios

**Files:** Modify `tests/test_api.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_workflow_endpoint_retention_concern_recommends_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pricing_copilot.workflow.get_default_synthesizer",
        lambda settings: FakeRecommendationSynthesizer(),
    )
    payload = _controlled_increase_payload()
    payload["scenario"] = "retention_concern"
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["action"] in ("hold", "decrease")
    assert body["missing_evidence"] == []


def test_workflow_endpoint_conflicting_evidence_forces_investigate() -> None:
    payload = _controlled_increase_payload()
    payload["scenario"] = "conflicting_evidence"
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["action"] == "investigate"
    assert body["recommendation"]["price_range"] is None
    assert body["missing_evidence"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api.py -v`

- [ ] **Step 3: Run again after Task 7 lands**

These tests need no `api.py` changes - `/workflow` already routes through `run_portfolio_workflow` for any scenario. Once Task 7's `workflow.py` changes are in place, rerun:
Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (all tests, including the two new ones).

- [ ] **Step 4: Commit**

```bash
git add tests/test_api.py
git commit -m "test: prove retention-concern and conflicting-evidence journeys via the API"
```

---

## Task 9: Live coverage for the new scenarios

**Files:** Modify `tests/test_recommendation_live.py`.

- [ ] **Step 1: Add a live retention-concern test (gated on credentials) and an unconditional conflicting-evidence test**

```python
@requires_azure_openai
def test_live_retention_concern_recommends_hold_or_limited_reduction_without_causal_language() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.RETENTION_CONCERN,
    )

    result = run_portfolio_workflow(question)

    assert result.recommendation.action in {RecommendationAction.HOLD, RecommendationAction.DECREASE}
    if result.recommendation.price_range is not None:
        assert result.recommendation.price_range.upper_pct <= 0

    combined_text = " ".join(
        [result.recommendation.rationale, *result.recommendation.counter_evidence]
    ).lower()
    for banned in ("caused", "led to", "resulted in", "drove", "due to"):
        assert banned not in combined_text


def test_conflicting_evidence_never_requires_model_credentials() -> None:
    """The material-evidence-issues gate must short-circuit before any model call, so this
    scenario is always testable even with no Azure OpenAI credentials configured."""
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
    )

    result = run_portfolio_workflow(question)

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.recommendation.price_range is None
```

Add `RecommendationAction` to the existing import block from `pricing_copilot.contracts` if not already present (it already is, from the #4 live test).

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_recommendation_live.py -v -s`
Expected: PASS (3 tests total - the original controlled-increase live test still passes, plus the two new ones). If the live retention-concern assertion on action fails because the real model proposes something outside `{HOLD, DECREASE}`, inspect the actual model output before changing anything - that would be a genuine finding about prompt quality, not a wiring bug.

- [ ] **Step 3: Commit**

```bash
git add tests/test_recommendation_live.py
git commit -m "test: add live retention-concern coverage and credential-free conflicting-evidence proof"
```

---

## Task 10: Full verification pass

- [ ] **Step 1: Run the full quality command**

Run: `./scripts/quality.sh`
Expected: Ruff, MyPy strict, Pytest, Bandit, and the secret scan all pass.

- [ ] **Step 2: Manual smoke test of all three scenarios via the CLI**

```bash
for scenario in controlled_increase retention_concern conflicting_evidence; do
  echo "=== $scenario ==="
  uv run pricing-copilot --product personal_motor --region north_west --segment renewal \
    --start-month 2026-01-01 --end-month 2026-06-01 --scenario "$scenario" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['recommendation']['action'], d['recommendation']['price_range'])"
done
```
Expected: `controlled_increase` -> `increase` with a bounded range; `retention_concern` -> `hold` or `decrease` with `null` or a non-positive range; `conflicting_evidence` -> `investigate` with `null`.

- [ ] **Step 3: Confirm #2-#5 behavior is untouched**

Run: `uv run pytest tests/test_workflow.py tests/test_decisions_service.py tests/test_api.py -v`
Expected: all pass, including the original controlled-increase assertions unchanged.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve quality command findings"
```
