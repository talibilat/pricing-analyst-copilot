# Interview Experience and Presentation Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps between the already-built governed workflow and a rehearsable interview package: render the confidence/fair-value/evidence-detail UI surfaces that exist on the backend but are invisible today, widen UI test coverage to the scenarios/actions the ticket requires, and produce the documentation and presentation artifacts (risk register, decision log, demonstration script, slide deck, screenshots) that do not exist yet.

**Architecture:** No new subsystems. This ticket is UI rendering completion (`streamlit_app.py` already has every data field it needs on `WorkflowResult`/`Recommendation`/`EvidenceLedger` - it just doesn't render several of them), UI test-surface expansion (`tests/test_streamlit_chat_e2e.py`), and net-new documentation/presentation files under `docs/`.

**Tech Stack:** Streamlit, `streamlit.testing.v1.AppTest`, Altair (existing chart library), self-contained HTML for the slide deck (published via the Artifact tool, also saved to the repo as a backup asset).

## Global Constraints

- The interview interface is chat-first; the legacy portfolio form is not the primary workflow and this plan does not add a portfolio-selection form (only one product/region/segment combination is supported across the whole product - the existing suggested-questions sidebar and scenario keywords already cover "portfolio selection" for the single supported combination).
- Visual design must be professional and neutral - no Aviva branding imitation.
- Never fabricate an activity, chart, or number that isn't backed by a real typed field already on `WorkflowResult`/`Recommendation`/`EvidenceLedger`/`PortfolioAnalytics`.
- Commercial value in the presentation must be framed as measurable shadow-mode hypotheses, never invented savings or loss-ratio numbers.
- No live model calls in new tests unless explicitly marked `@requires_azure_openai`, matching the existing pattern throughout this repo.
- Never use an em dash in any file this plan creates or edits - use a plain hyphen instead.
- Follow the existing TDD/quality-suite/commit cadence used throughout this repository for every code task: failing test -> verify red -> implement -> verify green -> commit, then `./scripts/quality.sh` before closing out.
- This agent cannot produce an actual screen recording (no video-capture tool exists in this environment) - the demonstration script must say so honestly rather than claim a recording was made.

---

### Task 1: Render confidence components and fair-value status

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py` (`_render_workflow_result`, roughly lines 63-113)
- Test: `tests/test_streamlit_chat_e2e.py`

**Interfaces:**
- Consumes: `Recommendation.confidence: ConfidenceBreakdown | None` (fields: `evidence_coverage`, `source_freshness`, `specialist_agreement`, `data_quality`, `conflict_penalty`, `overall`, all `float`, from `src/pricing_copilot/evidence/models.py`); `Recommendation.fair_value_status: FairValueStatus | None` (`NO_CONCERN`/`REVIEW_RECOMMENDED`/`CONCERN_IDENTIFIED`); `Recommendation.fair_value_follow_up: list[str]`.
- Produces: no new public functions - extends the existing `_render_workflow_result(result: WorkflowResult) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streamlit_chat_e2e.py (add to the existing file)
def test_recommendation_response_shows_confidence_and_fair_value() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Confidence" in markdown
    assert "Fair value" in markdown or "Fair-value" in markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -k confidence_and_fair_value -v`
Expected: FAIL - no "Confidence" or "Fair value" text anywhere in rendered markdown.

- [ ] **Step 3: Implement**

In `src/pricing_copilot/streamlit_app.py`, inside `_render_workflow_result`, right after the existing citations caption block (`if recommendation.cited_evidence_ids: st.caption(...)`), add:

```python
    if recommendation.confidence is not None:
        confidence = recommendation.confidence
        st.markdown("**Confidence**")
        cols = st.columns(5)
        labels_and_values = [
            ("Evidence coverage", confidence.evidence_coverage),
            ("Source freshness", confidence.source_freshness),
            ("Specialist agreement", confidence.specialist_agreement),
            ("Data quality", confidence.data_quality),
            ("Conflict penalty", confidence.conflict_penalty),
        ]
        for column, (label, value) in zip(cols, labels_and_values, strict=True):
            column.metric(label, f"{value * 100:.0f}%")
        st.caption(f"Overall confidence: {confidence.overall * 100:.0f}%")

    if recommendation.fair_value_status is not None:
        fair_value_labels = {
            FairValueStatus.NO_CONCERN: "No concern",
            FairValueStatus.REVIEW_RECOMMENDED: "Review recommended",
            FairValueStatus.CONCERN_IDENTIFIED: "Concern identified",
        }
        st.markdown(
            f"**Fair value status:** {fair_value_labels[recommendation.fair_value_status]}"
        )
        if recommendation.fair_value_follow_up:
            st.write("\n".join(f"- {item}" for item in recommendation.fair_value_follow_up))
```

Add the import at the top of the file:

```python
from pricing_copilot.evidence.models import FairValueStatus
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: render confidence components and fair-value status in the UI"
```

---

### Task 2: Render expandable evidence detail cards

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py`
- Test: `tests/test_streamlit_chat_e2e.py`

**Interfaces:**
- Consumes: `WorkflowResult.evidence_ledger: EvidenceLedger | None`, `EvidenceLedgerEntry` fields (`evidence_id`, `source_type`, `source_reference`, `source_date`, `metric_name`, `value`, `baseline_value`, `interpretation`) from `src/pricing_copilot/evidence/models.py`.
- Produces: a new `_render_evidence_detail(ledger: EvidenceLedger, cited_ids: list[str]) -> None` function, called from `_render_workflow_result`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streamlit_chat_e2e.py (add to the existing file)
def test_recommendation_response_shows_expandable_evidence_detail() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    assert app.expander
    expander_labels = [e.label for e in app.expander]
    assert any("Evidence detail" in label for label in expander_labels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -k evidence_detail -v`
Expected: FAIL - no expander labeled "Evidence detail" exists.

- [ ] **Step 3: Implement**

In `src/pricing_copilot/streamlit_app.py`, add the import:

```python
from pricing_copilot.evidence.models import EvidenceLedger
```

Add a new function near `_render_workflow_result`:

```python
def _render_evidence_detail(ledger: EvidenceLedger, cited_ids: list[str]) -> None:
    cited_entries = [entry for entry in ledger.entries if entry.evidence_id in cited_ids]
    if not cited_entries:
        return
    with st.expander(f"Evidence detail ({len(cited_entries)})", expanded=False):
        for entry in cited_entries:
            st.markdown(f"**{entry.evidence_id}** - {entry.source_type}")
            detail_line = f"Source: {entry.source_reference}"
            if entry.source_date is not None:
                detail_line += f" | Date: {entry.source_date.isoformat()}"
            st.caption(detail_line)
            if entry.metric_name is not None:
                metric_line = f"{entry.metric_name}: {entry.value}"
                if entry.baseline_value is not None:
                    metric_line += f" (baseline {entry.baseline_value})"
                st.write(metric_line)
            st.write(entry.interpretation)
            st.divider()
```

Call it from `_render_workflow_result`, immediately after the existing citations caption block:

```python
    if recommendation.cited_evidence_ids and result.evidence_ledger is not None:
        _render_evidence_detail(result.evidence_ledger, recommendation.cited_evidence_ids)
```

(Leave the existing `st.caption("Citations: " + ...)` line in place - the expander is additive detail, not a replacement.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: render expandable per-entry evidence detail cards"
```

---

### Task 3: Add claim-severity and competitor-movement charts, make counter-evidence prominent

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py`
- Test: `tests/test_streamlit_chat_e2e.py`

**Interfaces:**
- Consumes: `PortfolioAnalytics.claims.average_severity_gbp.monthly: list[MonthlyValue]`; `PortfolioAnalytics.competitors.competitors: list[CompetitorMovement]` (each with `.competitor_name: str` and `.price_index.monthly: list[MonthlyValue]`), from `src/pricing_copilot/analytics/contracts.py`.
- Produces: extends the existing `_render_time_series(months, series, *, y_label)` calls inside `_render_workflow_result`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streamlit_chat_e2e.py (add to the existing file)
def test_supporting_charts_include_severity_and_competitor_movement() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Claim severity" in markdown
    assert "Competitor" in markdown


def test_counter_evidence_uses_a_prominent_warning_block() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Replay the conflicting evidence scenario")
    app.run()

    assert not app.exception
    warning_bodies = "\n".join(w.body for w in app.warning)
    assert warning_bodies
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -k "severity_and_competitor or prominent_warning" -v`
Expected: FAIL - "Claim severity"/"Competitor" captions do not exist yet in the charts expander; counter-evidence is currently plain `st.write`, not `st.warning`.

- [ ] **Step 3: Implement**

In `src/pricing_copilot/streamlit_app.py`'s `_render_workflow_result`, inside the `with st.expander("Supporting charts", expanded=False):` block, add after the existing "Claims performance" chart:

```python
        st.caption("Claim severity")
        _render_time_series(
            [item.period for item in analytics.claims.average_severity_gbp.monthly],
            {
                "Average severity (GBP)": [
                    item.value for item in analytics.claims.average_severity_gbp.monthly
                ]
            },
            y_label="GBP per claim",
        )
```

and after the existing "Conversion performance" chart:

```python
        st.caption("Competitor price movement")
        _render_time_series(
            [item.period for item in analytics.competitors.competitors[0].price_index.monthly]
            if analytics.competitors.competitors
            else [],
            {
                competitor.competitor_name: [
                    item.value for item in competitor.price_index.monthly
                ]
                for competitor in analytics.competitors.competitors
            },
            y_label="Price index",
        )
```

Replace the existing plain counter-evidence rendering:

```python
    if recommendation.counter_evidence:
        st.markdown("**Counter-evidence**")
        st.write("\n".join(f"- {item}" for item in recommendation.counter_evidence))
```

with a visually prominent warning block:

```python
    if recommendation.counter_evidence:
        st.warning(
            "**Counter-evidence**\n\n"
            + "\n".join(f"- {item}" for item in recommendation.counter_evidence),
            icon="⚖️",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: add severity/competitor charts and make counter-evidence prominent"
```

---

### Task 4: Widen UI end-to-end test coverage

**Files:**
- Modify: `tests/test_streamlit_chat_e2e.py`

**Interfaces:**
- Consumes: `AppTest` (`streamlit.testing.v1`), the chat surfaces built in Tasks 1-3 and issues #9-#11.
- Produces: no new production code - test-only task.

- [ ] **Step 1: Write the new tests**

```python
# tests/test_streamlit_chat_e2e.py (add to the existing file)
def test_claims_only_query_returns_a_single_table() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show claims performance")
    app.run()

    assert not app.exception
    assert len(app.dataframe) == 1
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Getting information from claims performance data" in markdown


def test_analyse_everything_shows_specialist_supervisor_coordination() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Supervisor coordinating specialist agents" in markdown
    assert "Recommendation:" in markdown or "Proposed action" in markdown


def test_evaluation_question_renders_the_targets_vs_actuals_table_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show me the evaluation results")
    app.run()

    assert not app.exception
    assert app.dataframe


def test_drift_question_renders_the_material_alert_table_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Show me drift monitoring")
    app.run()

    assert not app.exception
    assert app.dataframe


def test_retention_concern_scenario_is_reachable_by_keyword() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value(
        "What did competitors do in the retention concern scenario?"
    )
    app.run()

    assert not app.exception
    assert app.dataframe


def test_an_unsafe_request_is_refused_in_the_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("SELECT * FROM claims")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "cannot accept raw SQL" in markdown.lower()


def test_analyst_can_record_an_approval_decision_from_the_chat_ui() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=30)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    assert app.checkbox
    confirm_checkbox = app.checkbox[-1]
    confirm_checkbox.set_value(True)
    app.run()

    assert app.button
    submit_buttons = [b for b in app.button if "Record analyst decision" in b.label]
    assert submit_buttons
    submit_buttons[0].click()
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    assert "recorded" in markdown.lower() or app.success
```

- [ ] **Step 2: Run the new tests and fix anything genuinely broken**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`

Expected: most should PASS immediately since they exercise already-working paths (Tasks 1-3 and issues #9-#11 built the underlying behavior; this task only adds UI-level proof). If `test_analyst_can_record_an_approval_decision_from_the_chat_ui` fails because `app.checkbox`/`app.button` selectors don't match Streamlit's `AppTest` API exactly, inspect the actual `AppTest` tree with a throwaway script (`uv run python -c "from streamlit.testing.v1 import AppTest; ..."`, print `app.checkbox`/`app.button` reprs) and adjust the selector - do not weaken the assertion's intent (a real decision must actually get recorded).

- [ ] **Step 3: Commit**

```bash
git add tests/test_streamlit_chat_e2e.py
git commit -m "test: widen UI end-to-end coverage to single-source, analyse-everything, evaluation, drift, retention_concern, refusal, and decision-recording paths"
```

---

### Task 5: Narrow-viewport and keyboard verification pass

**Files:**
- None created - manual browser verification, fixing anything real it finds.

**Interfaces:**
- None.

- [ ] **Step 1: Start the app and screenshot at desktop width**

Use `mcp__Claude_Browser__preview_start` with name `streamlit`, then `mcp__Claude_Browser__resize_window` with `preset: "desktop"`, take a screenshot of the default controlled_increase view.

- [ ] **Step 2: Resize to a narrow viewport and screenshot**

Use `mcp__Claude_Browser__resize_window` with `preset: "mobile"` (375x812). Take a screenshot. Check specifically: does the "Confidence" `st.columns(5)` metric row (Task 1) wrap or clip? Does the Monitoring tab's alert text overflow? Streamlit's `st.columns` reflows narrow automatically in recent versions - if the 5-column confidence row visibly clips or overlaps at 375px, replace `st.columns(5)` with a single `st.write` listing `label: value` pairs one per line instead (simpler, always narrow-safe) - only make this change if the screenshot shows a real problem.

- [ ] **Step 3: Verify keyboard operability**

Use `mcp__Claude_Browser__computer` with `action: "key"` to `Tab` through the page from the chat input, confirming focus visibly lands on the input, send button, and tab selector in a sensible order (Streamlit's native HTML controls handle this by default - this step is a verification, not new code, unless something is actually broken).

- [ ] **Step 4: Fix anything genuinely broken, otherwise move on**

If Steps 2-3 found a real clipping or focus-order problem, fix it with the minimal Streamlit-native change (no custom CSS/ARIA injection - prefer `st.columns` -> single-column fallback, or reordering `st.write` calls) and re-verify. If nothing is broken, no commit is needed for this task - record in the closing issue comment that narrow-viewport and keyboard behavior were verified with no code changes required.

---

### Task 6: Write the risk register

**Files:**
- Create: `docs/risk_register.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Write the file**

Create `docs/risk_register.md` covering, as a table (Risk | Description | Likelihood | Impact | Mitigation | Owner), every category the ticket names: model failure, arithmetic error, prompt injection, stale or missing data, automation bias, latency, cost, interface failure, demo failure. Ground every mitigation in a real, already-built control from this codebase (do not invent controls) - for example:

```markdown
# Risk Register

Risks specific to the Pricing Decision Copilot prototype and how this codebase mitigates each one today.
Likelihood and impact are qualitative (Low/Medium/High), scoped to the interview prototype, not a production deployment.

| Risk | Description | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| Model failure | The Azure OpenAI endpoint is unreachable, times out, or returns invalid output during a live run. | Medium | Medium | `orchestration/pipeline.py` wraps `get_default_orchestration` failures into a safe `data_quality_investigation_result`; the chat layer detects a `workflow:`-prefixed failure reason and offers an explicit, clearly labeled replay instead of silently degrading (`chat/service.py::_run_pricing_analysis`). Three real replay artifacts are committed under `var/replay/` as an offline fallback. | Talib |
| Arithmetic error | A deterministic metric (loss ratio, movement percentage, clamp) is computed incorrectly. | Low | High | All numeric calculation lives in `analytics/calculators.py` and `recommendation/governance.py`, both covered by dedicated unit tests (`tests/test_analytics_calculators.py`, `tests/test_recommendation_governance.py`) and by golden-set deterministic cases (`GC-13`, `GC-14` in `evaluation/golden_set.py`) that assert exact clamp and rejection behavior. | Talib |
| Prompt injection | Adversarial content embedded in retrieved documents attempts to alter model behavior or leak instructions. | Medium | High | `governance/security.py::quarantine_unsafe_documents` strips flagged content before it reaches any model call; golden-set cases GC-11/GC-12/GC-16/GC-17 (`evaluation/golden_set.py`) exercise document-embedded injection, direct override attempts, customer-level requests, and raw-SQL attempts, all measured at 0% success in the last recorded evaluation run (`var/evaluation/latest.json`). | Talib |
| Stale or missing data | A scenario's evidence documents or structured data fall outside the freshness window. | Medium | Medium | `evidence/policy.py::detect_material_evidence_issues` and the `conflicting_evidence` scenario's deliberately gapped conversion data (`data/generation.py::CONFLICTING_EVIDENCE_CONVERSION_MONTHS`) exercise this path; drift monitoring's data detector flags month-25 shifts explicitly with baseline-window and insufficient-sample reporting (`drift/data_detector.py`). | Talib |
| Automation bias | An analyst defers to the recommendation without engaging with counter-evidence or confidence signals. | Medium | Medium | Counter-evidence renders as a prominent warning block, not buried text (`streamlit_app.py::_render_workflow_result`); confidence components and fair-value status are shown alongside every recommendation; every recorded decision requires an explicit confirmation checkbox and a written rationale (`streamlit_app.py::_render_decision_controls`) before it is written to the separate, append-only SQLite decision log. | Talib |
| Latency | A live workflow run exceeds a reasonable interview-demo wait. | Low | Medium | Bounded timeouts and retries are enforced by `orchestration/runtime.py::AgentRuntime` (`max_workflow_seconds`, `tool_timeout_seconds`, `max_retries` in `Settings`); the real measured P95 latency in the last evaluation run was 17.0s against a 30s target (`var/evaluation/latest.json`). Replay artifacts provide an instant fallback. | Talib |
| Cost | Live model calls during rehearsal or the interview itself accumulate unexpected token cost. | Low | Low | `CostSettings` and `TokenUsage.estimated_cost_gbp` track every call; the last evaluation run recorded a total cost of GBP 0.0 against the configured rate; replay mode requires zero live calls for the rehearsed demo path. | Talib |
| Interface failure | The Streamlit process crashes, hangs, or the browser session drops mid-demonstration. | Low | High | The CLI (`uv run pricing-copilot`) and the committed replay artifacts provide a complete non-Streamlit fallback path for every designed scenario; see `docs/demonstration_script.md` for the exact fallback transitions. | Talib |
| Demo failure | Any of the above compounds during the live interview window. | Low | High | The demonstration script names an explicit fallback transition at every step (see `docs/demonstration_script.md`); screenshots under `docs/screenshots/` and the pre-generated evaluation/drift reports under `var/` are available offline with no live dependency. | Talib |
```

- [ ] **Step 2: Commit**

```bash
git add docs/risk_register.md
git commit -m "docs: add the risk register"
```

---

### Task 7: Write the decision log

**Files:**
- Create: `docs/decision_log.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Write the file**

Create `docs/decision_log.md` recording the major choices actually made across this build, one entry per decision with Context / Decision / Consequence, grounded in what genuinely happened (do not invent decisions):

```markdown
# Decision Log

Major product, architecture, policy, testing, and delivery decisions made while building this prototype, in the order they were made.

## Governed multi-agent orchestration over a single large prompt

**Context:** A single LLM call could plausibly produce a pricing recommendation with much less code.
**Decision:** Split the workflow into a Portfolio Supervisor coordinating four evidence specialists (claims, conversion, market intelligence, pricing history), an isolated Recommendation Agent that never sees raw data, and an independent Governance Agent that checks the recommendation against policy.
**Consequence:** More code and more agent calls, but the recommendation step cannot fabricate evidence it never received, and governance runs as a genuinely separate check rather than the same model grading its own work. The single-agent baseline is retained specifically so the golden evaluation benchmark can show this tradeoff with real numbers rather than asserting it.

## Deterministic calculation kept entirely outside the model

**Context:** Loss ratios, movement percentages, and the price-movement clamp are the numbers an analyst will scrutinize hardest.
**Decision:** Every number the recommendation cites is computed by plain Python in `analytics/calculators.py` and clamped by `recommendation/governance.py`, never by the model. The model only narrates already-computed numbers.
**Consequence:** A model hallucination cannot produce a wrong number, only a wrong sentence about a correct number - and the golden evaluation set's deterministic cases (GC-13, GC-14, GC-15) can assert exact values.

## Chat-first interface, not a portfolio-selection form

**Context:** The original prototype (issue #2) shipped a form-based portfolio selector.
**Decision:** Issue #12's chat-first rebuild (built primarily in the earlier chat-first foundation work) made natural-language chat the primary surface; the form is not the primary workflow, and because only one product/region/segment combination is supported, no portfolio-selection UI was added back - scenario and source selection happen through chat keywords and the suggested-questions sidebar instead.
**Consequence:** The interview demo opens directly into a working conversation with zero setup, at the cost of not exercising a portfolio-selection UI pattern that would only matter if more than one portfolio combination existed.

## Replay artifacts as the resilience story, not silent live-to-cache fallback

**Context:** A live Azure OpenAI failure during the interview would be the worst possible failure mode.
**Decision:** When a live run fails, the chat surface reports the failure honestly and offers an explicit "replay the X scenario" action rather than silently substituting cached data (`chat/service.py::_run_pricing_analysis`). Every ChatResponse and WorkflowResult carries a `source: ResultSource` field so replay output is always visibly labeled.
**Consequence:** An analyst - or an interviewer - can never mistake a cached run for a live one, which matters more for trust than a seamless-looking fallback would.

## Golden evaluation set exceeds every stated minimum

**Context:** The spec set minimums of fifteen total cases and two prompt-injection cases.
**Decision:** Built eighteen cases including four prompt-injection/adversarial cases (GC-11, GC-12, GC-16, GC-17) and one multi-turn conversational case (GC-18), rather than stopping at the stated minimums.
**Consequence:** More coverage of the security-critical path than strictly required, at the cost of a slightly larger golden set to maintain; the last live run measured 18/18 passed with zero failures and zero prompt-injection successes.

## Month-25 drift dataset as a new ScenarioName, not an extended existing scenario

**Context:** The drift-monitoring journey needed a reproducible dataset engineered to trigger known drift signals.
**Decision:** Added `ScenarioName.DRIFT_MONITORING` as a fourth, deliberately non-priceable scenario (excluded from `IMPLEMENTED_DATA_SCENARIOS`) rather than extending one of the three existing 24-month scenarios to 25 months.
**Consequence:** Keeps monitoring-only data cleanly separated from priceable scenario data, at the cost of a version bump to `ANALYTICS_DATABASE_VERSION` so existing on-disk databases pick up the new scenario.

## Presentation package built as a self-contained HTML deck, not PowerPoint or Google Slides

**Context:** The ticket asks for ten main slides plus a technical appendix, with no format mandated.
**Decision:** Built as a single self-contained HTML file, viewable directly in a browser and publishable as an Artifact, rather than a PowerPoint or Google Slides file that would require external tooling this agent does not have credentialed access to.
**Consequence:** Fully portable and version-controllable alongside the code, at the cost of not being natively editable in PowerPoint/Keynote if a more conventional format is later wanted for the actual interview.
```

- [ ] **Step 2: Commit**

```bash
git add docs/decision_log.md
git commit -m "docs: add the decision log"
```

---

### Task 8: Write the six-minute demonstration script

**Files:**
- Create: `docs/demonstration_script.md`

**Interfaces:**
- Consumes: the three designed scenarios, replay artifacts, evaluation/drift chat intents, all already built.

- [ ] **Step 1: Write the file**

Create `docs/demonstration_script.md` as a timed walkthrough with an explicit fallback named at every step:

```markdown
# Six-Minute Demonstration Script

Primary path: the chat interface (`uv run streamlit run src/pricing_copilot/streamlit_app.py`), Chat tab, controlled_increase scenario (the default on load - no setup needed).

| Time | Step | What to say / do | Fallback if this step fails |
|---|---|---|---|
| 0:00-0:30 | Open | App is already on the controlled_increase scenario. Point out the chat transcript, suggested questions, and the caption stating the copilot never executes a pricing change. | If Streamlit fails to start: open a terminal and run `uv run pricing-copilot --product personal_motor --region north_west --segment renewal --start-month 2025-07-01 --end-month 2025-12-01` instead, and narrate from the CLI's readable summary output. |
| 0:30-1:30 | Ask "Analyse everything and recommend a pricing action" | Narrate the visible activity trace as it appears: Portfolio Supervisor coordinating, then each specialist (claims, conversion, market intelligence, pricing history) in turn, then the recommendation and governance agents. Point out this is real typed trace data, not a fabricated timer. | If the live call fails: the UI will show "Live analysis could not complete" with a "Try replay instead" button - click it and narrate that the replay is clearly labeled REPLAY MODE, not a live analysis. |
| 1:30-2:30 | Read the result | Walk through: proposed action and range, rationale, the counter-evidence warning block, confidence components, fair-value status, and the expandable evidence detail cards (source type, date, identifier, metric). | If any component is empty (e.g., no counter-evidence for this run): say so plainly - "no counter-evidence was found this run" is itself evidence the system doesn't fabricate content. |
| 2:30-3:15 | Ask "What did competitors do in the retention concern scenario?" | Shows scenario switching by keyword, and a data-retrieval-only answer (no recommendation) to demonstrate the copilot doesn't force a recommendation when one wasn't asked for. | If retention_concern data looks wrong: fall back to the pre-generated replay artifact for retention_concern (`var/replay/retention_concern.json`) by asking "Replay the retention concern scenario" instead. |
| 3:15-4:00 | Record an analyst decision | On the controlled_increase recommendation from step 2, open "Confirm and record an analyst decision," select Approve with Conditions, write a one-line rationale, confirm the checkbox, submit. Point out the success message and that this is a separate, append-only SQLite log - it never executes anything. | If the form doesn't submit: narrate the intended flow from the screenshot in `docs/screenshots/decision_controls.png` instead. |
| 4:00-4:45 | Ask "Show me the evaluation results" | Shows the targets-vs-actuals table - 18/18 governed cases, every hard target met or beaten, pulled from a real pre-generated report (`var/evaluation/latest.json`), not invented for the demo. | If no report is loaded: run `uv run pricing-copilot --evaluate` live in a terminal (takes under three minutes against real cases; use the pre-generated report and narrate from `docs/screenshots/evaluation_view.png` if time is short). |
| 4:45-5:30 | Switch to the Monitoring tab | Shows the month-25 drift journey: six material data-domain alerts (claim severity, frequency, loss ratio, conversion, competitor index, feedback topics), each with its baseline window, threshold, and the specific statistical measure that crossed it (z-score, percentage movement, KS-test, PSI). Point out behavior/operational/configuration alerts are all clean. | If the tab is empty: the pre-generated report is committed at `var/drift/latest.json` - restart the app to reload it, or narrate from `docs/screenshots/monitoring_tab.png`. |
| 5:30-6:00 | Close | State the thesis: this is a governed evidence workflow with a human decision-maker at the end, not an LLM acting as a pricing engine - every number is deterministic Python, every model output is checked by an independent governance step, and nothing here ever executes a price change. | N/A - closing statement, no live dependency. |

## Honesty note on the backup recording

No screen recording of this demonstration exists. This agent has no video-capture tool available in this environment. The fallback for a live-demo failure is the CLI path and the screenshots under `docs/screenshots/`, not a pre-recorded video - if a recorded backup is wanted, capture it manually by running through this script once with screen recording on before the interview.
```

- [ ] **Step 2: Commit**

```bash
git add docs/demonstration_script.md
git commit -m "docs: add the six-minute demonstration script with named fallbacks"
```

---

### Task 9: Update README architecture/status sections

**Files:**
- Modify: `README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Fix the stale status line**

Find the line near `README.md:16` reading something like "Issues #2 through #8 are implemented" and update it to accurately reflect that issues #2-#11 are implemented and closed, issue #12 is in progress.

- [ ] **Step 2: Add human-authority and production-integration-boundary language to the Architecture section**

In the `## Architecture` section, after the existing Mermaid diagram and prose, add a short paragraph:

```markdown
Human authority is structural, not a UI convention: no code path in this repository can execute a pricing change. `AnalystDecisionType` (approve, approve with conditions, reject, investigate) is recorded to a separate, append-only SQLite log (`decisions/store.py`) and nothing downstream of that log exists - there is no execution path for it to feed into. Every recommendation is explicitly captioned as decision support requiring qualified analyst review, not a claim of automated pricing authority.

Production integration boundaries: this prototype's DuckDB analytics store and SQLite decision log stand in for a production data warehouse and a production decision-audit system respectively. A production integration would replace `PersistentAnalyticsDatabase` with a read replica of the real pricing data warehouse behind the same typed `query_source` interface, and would replace the SQLite decision store with the real underwriting decision-audit system - the `DecisionRequest`/`AnalystDecision` contracts are already shaped to make that swap a storage-layer change, not an application-logic change.
```

- [ ] **Step 3: Cross-link the new documentation**

Add a short subsection right after "## Interview thesis" (or wherever the file currently ends its narrative sections, before "## Delivery roadmap" if that comes later) pointing to the new docs:

```markdown
## Supporting documents

- [Risk register](docs/risk_register.md)
- [Decision log](docs/decision_log.md)
- [Demonstration script](docs/demonstration_script.md)
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README architecture section and cross-link new documents"
```

---

### Task 10: Build the presentation deck

**Files:**
- Create: `docs/presentation/index.html`

**Interfaces:**
- None (static HTML/CSS/JS, self-contained per the Artifact tool's constraints - no external requests, inline styles).

- [ ] **Step 1: Load the artifact-design skill**

Before writing the file, load the `artifact-design` skill (required before any Artifact publish) to calibrate visual design for this specific deliverable - a professional, neutral, presentation-style deck, not a playful widget.

- [ ] **Step 2: Write the ten main slides plus technical appendix**

Build `docs/presentation/index.html` as a self-contained slide deck (CSS-only slide-by-slide navigation with `<section class="slide">` blocks styled with `scroll-snap` or simple show/hide via a small inline `<script>`, no external libraries). Structure:

1. **Title** - "Pricing Decision Copilot" / "A governed evidence workflow for portfolio pricing decisions" / presenter name / date.
2. **The business problem** - UK personal motor pricing analysts spend disproportionate time gathering evidence across claims, conversion, competitor, and market-intelligence sources before they can even start reasoning about a pricing action.
3. **What this is not** - not an LLM pricing engine, not a system that executes pricing changes, not trained on or using any real Aviva data.
4. **Architecture** - the manager-style orchestration diagram (Portfolio Supervisor -> four specialists -> evidence ledger -> isolated Recommendation Agent -> independent Governance Agent -> human review), reusing the same structure as the README's Mermaid diagram, rendered as a simple boxes-and-arrows SVG or styled HTML, not a screenshot.
5. **Governance in depth** - deterministic calculation outside the model, the ±5% policy clamp, document quarantine against prompt injection, the approved-agent registry, bounded retries/timeouts.
6. **Evidence and citations** - every recommendation cites specific evidence entries with source type/date/identifier; counter-evidence is never hidden.
7. **Evaluation evidence** - the golden set (18 cases, four security cases, one multi-turn case), the real measured results from `var/evaluation/latest.json` (18/18 passed, every hard target met or beaten - use the real numbers, read the file before writing this slide).
8. **Drift monitoring** - the month-25 journey, four alert categories, real measured results from `var/drift/latest.json` (17 alerts, 6 material - use the real numbers).
9. **Delivery approach** - built end-to-end by a coding agent working ticket-by-ticket against a written spec, strict TDD, full quality suite (lint/type/test/security/secret-scan) gating every commit.
10. **Production roadmap and commercial framing** - prototype (this) -> shadow mode (run alongside human analysts, measure agreement rate and time-to-recommendation as hypotheses, not savings) -> limited pilot (a small analyst cohort, human-in-the-loop only) -> platform scale. Commercial value is explicitly framed as measurable shadow-mode hypotheses (e.g. "time-to-first-recommendation reduced by X%, to be measured, not assumed") - never an invented savings or loss-ratio number.

**Technical appendix** (a distinct section after the ten main slides, same file):
- Data model (the four structured sources, the unstructured document corpus, the persistent versioned DuckDB).
- Prompt-injection defense in depth (quarantine function, four dedicated golden-set cases, real 0% success rate).
- Evaluation case catalogue (all 18 cases by category, referencing `evaluation/golden_set.py`).
- Coding-agent delivery model (ticket-by-ticket, TDD, one plan document per ticket under `docs/superpowers/plans/`, full quality suite per commit).
- Risk register summary (link to `docs/risk_register.md`, list the nine risk categories).
- Production architecture (the integration-boundary paragraph from Task 9, expanded with the specific swap points: DuckDB -> data warehouse read replica, SQLite -> decision-audit system, Azure OpenAI dev deployment -> production model routing/rate limits).
- Cost and latency drivers (token usage and estimated cost fields already tracked by `TokenUsage`; P95 latency measured at 17.0s against a 30s target in the last evaluation run - use the real number).

Add a small `<footer>` on every slide noting the target pacing: "17-18 minutes total, ~90 seconds per main slide, appendix on request."

- [ ] **Step 3: Publish as an Artifact**

Use the `Artifact` tool with `file_path: "docs/presentation/index.html"`, a `title`, a one-sentence `description`, and a favicon emoji (e.g. "📊"). This makes the deck viewable and shareable independent of the repository.

- [ ] **Step 4: Commit the source file to the repository as the offline backup**

```bash
git add docs/presentation/index.html
git commit -m "docs: add the interview presentation deck"
```

---

### Task 11: Capture demonstration screenshots

**Files:**
- Create: `docs/screenshots/controlled_increase_recommendation.png`
- Create: `docs/screenshots/decision_controls.png`
- Create: `docs/screenshots/evaluation_view.png`
- Create: `docs/screenshots/monitoring_tab.png`

**Interfaces:**
- None (browser screenshots saved as files, referenced by `docs/demonstration_script.md`, already written in Task 8 to reference exactly these four filenames).

- [ ] **Step 1: Start the app and capture each state**

Using `mcp__Claude_Browser__preview_start`/`navigate`/`computer` (screenshot action), capture, in order: (a) a completed controlled_increase recommendation with confidence/fair-value/evidence-detail all visible (the Task 1-2 UI), (b) the decision-controls expander open with a rationale filled in before submission, (c) the evaluation targets-vs-actuals table, (d) the Monitoring tab with the material-alerts banner and at least one expanded category.

Save each screenshot to the exact path listed above - the browser tool's screenshot output is returned as image data; write it to disk at the target path (if the tool does not support direct file save, take the screenshot, then use it to confirm the state is correct, and separately use a scripted headless capture or the OS screenshot mechanism available to save the file - whichever this environment actually supports).

- [ ] **Step 2: Commit**

```bash
git add docs/screenshots/
git commit -m "docs: add demonstration screenshots"
```

---

### Task 12: Final quality suite, full scenario smoke test, push, and close

**Files:**
- None created - verification and closing task.

- [ ] **Step 1: Regenerate the pre-generated demo evaluation and drift reports**

```bash
uv run pricing-copilot --evaluate
uv run pricing-copilot --monitor-drift
```

Confirm the printed summaries match what Task 10's presentation slides and Task 8's demonstration script cite (18/18 governed cases, 17 alerts/6 material). If the numbers drifted from what was written into the presentation/script, update those two files to match the freshly regenerated real numbers - never leave stale numbers in interview-facing material.

- [ ] **Step 2: Run the full quality suite**

```bash
./scripts/quality.sh
```

Expected: Ruff, MyPy strict, full pytest, Bandit, and the secret scan all pass with exit code 0. Fix anything the suite surfaces before proceeding, following the established discipline of this repository (investigate root causes, do not weaken checks).

- [ ] **Step 3: Manual full-scenario browser smoke test**

Walk through the full `docs/demonstration_script.md` script once in the browser end to end (controlled_increase recommendation with confidence/fair-value/evidence-detail, retention_concern data-only query, a recorded decision, the evaluation view, the Monitoring tab), confirming every step matches what the script and screenshots claim.

- [ ] **Step 4: Secret-scan and commit any remaining regenerated artifacts**

```bash
grep -i -E "api[_-]?key|AZURE_OPENAI|sk-|secret|password" var/evaluation/latest.json var/drift/latest.json
git add var/evaluation/latest.json var/drift/latest.json
git status --short
git commit -m "chore: refresh demo evaluation and drift reports"
```

(Only commit if the regenerated files actually differ from what's already committed - check `git status` first.)

- [ ] **Step 5: Push**

```bash
git push origin main
```

- [ ] **Step 6: Close issue #12**

Use `gh issue close 12 --comment "..."` with a detailed summary covering: the four UI rendering gaps closed (confidence, fair-value, evidence detail, severity/competitor charts, prominent counter-evidence), the widened UI test coverage, the narrow-viewport/keyboard verification outcome, the three new documentation files, the presentation deck and its Artifact URL, the screenshots, and confirmation that the full quality suite and a real end-to-end demonstration walkthrough both passed.

---

## Self-Review Notes

**Spec coverage:**
- Controlled-increase-on-load, coherent workflow sequence, chart legibility (loss ratio + conversion already done; severity + competitor added Task 3), evidence expandability (Task 2), counter-evidence prominence (Task 3), distinct loading/empty/error/live/replay states (already done, verified not re-built), keyboard/responsive/no-clipping (Task 5), professional neutral design (governs every UI task), UI test coverage across scenarios/actions/replay/evaluation/drift (Task 4) - all covered.
- Architecture doc (human authority + production boundaries, Task 9), risk register (Task 6), decision log (Task 7), demonstration script with named fallbacks (Task 8), presentation with appendix (Task 10), commercial value as shadow-mode hypotheses not invented savings (explicit in Task 10 slide 10), production roadmap prototype->shadow->pilot->platform (Task 10 slide 10), screenshots/CLI backup/pre-generated evaluation report (Task 11 + the CLI already existing + Task 12 Step 1), closing thesis on governed evidence workflow not LLM-as-pricing-engine (Task 8's closing step and Task 10 slide 3/10) - all covered.
- Chat-first requirements (opening screen, natural-language queries, governed retrieval, typed intents/query plans, prohibited actions, follow-ups, "analyse everything" routing, activity messages, agent statuses, citations/tables/charts in conversation, analyst actions from chat, evaluation/drift discoverable from chat) - confirmed already built across issues #6/#7/#9/#10/#11 per the exploration pass; this plan does not re-build any of it, only closes the specific rendering/testing gaps found.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code or fully-written prose content (the risk register, decision log, and demonstration script are written in full in the plan itself, not described).

**Type consistency:** `FairValueStatus`/`ConfidenceBreakdown`/`EvidenceLedgerEntry` field names used in Tasks 1-2 match `src/pricing_copilot/evidence/models.py` exactly as read from the source file. `_render_evidence_detail(ledger: EvidenceLedger, cited_ids: list[str])` signature is used consistently between its definition and call site in Task 2.

**Known scope decision to flag when closing the issue:** Task 5 (accessibility/responsive) is scoped as verification-plus-targeted-fix rather than a new custom CSS/ARIA subsystem, since Streamlit's native controls already provide baseline keyboard/ARIA support and hand-rolled accessibility work risks fighting the framework. Task 10's presentation format (self-contained HTML rather than PowerPoint/Slides) is a deliberate tooling choice recorded in the decision log (Task 7) - flag it explicitly when closing the issue in case the user wants a different format for the actual interview.
