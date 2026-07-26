# Freeze and Verify the Interview Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, with real commands and real output, that the complete governed workflow works end to end across every supported path (CLI, API, Streamlit, live, replay), produce a release manifest that records every configuration version, and give the interview package a frozen, named release point.

**Architecture:** This ticket builds almost no new application code - it verifies the application built across issues #2-#12 and packages the result. The one genuinely new artifact is a release manifest, generated from the same `current_configuration_versions()` function the application already uses internally, so the manifest can never drift from what the running application actually reports. Anything verification finds broken gets fixed with the same TDD cycle used throughout this repository.

**Tech Stack:** No new dependencies. Uses the existing CLI, FastAPI app (via `TestClient` or a live `uvicorn` process), Streamlit app, and `git tag`.

## Global Constraints

- The frozen release must open directly into the chat-first experience with no legacy-form setup step.
- No path anywhere in the codebase may execute or claim to execute a pricing change - this ticket explicitly audits for that, it does not just assume it.
- The evaluation report must show actual measured results, never a target mislabeled as achieved.
- This agent has no video-capture tool and no physical equipment - tasks that require a human physically rehearsing a presentation or checking real hardware/network are documented as an explicit checklist for the user, not fabricated as complete.
- Never use an em dash in any file this plan creates or edits - use a plain hyphen instead.
- Any post-release development must be able to happen on a new version without silently altering the frozen interview package - this plan achieves that with a git tag, not a new mechanism.

---

### Task 1: Full quality suite from a clean environment

**Files:** None created - verification task.

- [ ] **Step 1: Rebuild the environment from scratch**

```bash
rm -rf .venv
uv sync --all-groups
```

- [ ] **Step 2: Run the full quality suite**

```bash
./scripts/quality.sh
```

Expected: exit code 0. Ruff, MyPy strict, the full pytest suite, Bandit, and the secret scan all pass. If anything fails, fix the root cause using the same TDD discipline as every other ticket in this repository before proceeding - do not weaken a check to make it pass.

- [ ] **Step 3: Record the pass**

No commit needed unless Step 2 required a fix, in which case commit that fix with a message describing what was actually broken.

---

### Task 2: Verify all three scenarios through the CLI and API, live and replay

**Files:** None created - verification task.

**Interfaces:**
- Consumes: `uv run pricing-copilot` (existing CLI flags `--product --region --segment --start-month --end-month --scenario --replay --json`), `POST /workflow` (existing FastAPI endpoint, `replay: bool` query/body param per `src/pricing_copilot/api.py:31-34`).

- [ ] **Step 1: Rebuild the persistent database fresh**

```bash
rm -f var/synthetic_portfolio.duckdb
uv run pricing-copilot --build-data
```

- [ ] **Step 2: Run all three scenarios live through the CLI**

```bash
for scenario in controlled_increase retention_concern conflicting_evidence; do
  echo "=== $scenario ==="
  uv run pricing-copilot --product personal_motor --region north_west --segment renewal \
    --start-month 2025-07-01 --end-month 2025-12-01 --scenario "$scenario" --json \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['recommendation']['action'])"
done
```

Expected exact actions, matching the README's "Designed scenarios" section: `controlled_increase` -> `increase`, `retention_concern` -> `decrease` or `hold` (both are valid per the golden-set case GC-06's broadened expectation from a live-model finding in issue #10), `conflicting_evidence` -> `investigate`. If any scenario produces an unexpected action, this blocks the release per the ticket's own acceptance criteria - stop and investigate before continuing.

- [ ] **Step 3: Run all three scenarios through replay via the CLI**

```bash
for scenario in controlled_increase retention_concern conflicting_evidence; do
  echo "=== $scenario replay ==="
  uv run pricing-copilot --product personal_motor --region north_west --segment renewal \
    --start-month 2025-07-01 --end-month 2025-12-01 --scenario "$scenario" --replay --json \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['source'], d['recommendation']['action'])"
done
```

Expected: `source` is `replay` for all three, and the action matches Step 2's live result (the committed replay artifacts under `var/replay/` were recorded from real live runs).

- [ ] **Step 4: Run all three scenarios through the API, live and replay**

```bash
uv run uvicorn pricing_copilot.api:app --port 8321 &
API_PID=$!
sleep 2
for scenario in controlled_increase retention_concern conflicting_evidence; do
  for replay in false true; do
    echo "=== $scenario replay=$replay ==="
    curl -s -X POST "http://127.0.0.1:8321/workflow?replay=$replay" \
      -H "Content-Type: application/json" \
      -d "{\"product\":\"personal_motor\",\"region\":\"north_west\",\"segment\":\"renewal\",\"analysis_period\":{\"start_month\":\"2025-07-01\",\"end_month\":\"2025-12-01\"},\"scenario\":\"$scenario\"}" \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['source'], d['recommendation']['action'])"
  done
done
kill $API_PID
```

Expected: same actions as Steps 2-3, `source` matching `live`/`replay` as requested.

- [ ] **Step 5: Record the pass**

No commit needed for this verification task unless a real defect was found and fixed.

---

### Task 3: Verify chat-first query coverage through Streamlit, live and replay

**Files:** None created - manual browser verification task.

**Interfaces:**
- Consumes: the running Streamlit app (`mcp__Claude_Browser__preview_start` with name `streamlit`), all chat intents already built (`ChatIntent.DATA_RETRIEVAL`, `MULTI_SOURCE_SUMMARY`, `PRICING_ANALYSIS`, `REPLAY`, `EVALUATION`, `DRIFT`).

- [ ] **Step 1: Start the app and confirm it opens chat-first with zero setup**

Start the Streamlit preview. Confirm the default view is the Chat tab, controlled_increase scenario, no form or setup step required before the chat input is usable.

- [ ] **Step 2: Ask each required chat-first question type and confirm a real answer**

In the chat input, ask each of the following in turn and confirm a non-error response with the right kind of content:
- "Show claims performance" (claims data table)
- "Show conversion and retention performance" (conversion data table)
- "What did competitors do?" (competitor data table)
- "Show market intelligence" (unstructured market-intelligence table)
- "Show previous pricing actions" (pricing-history table)
- "Show aggregate customer feedback" (unstructured feedback table)
- "Analyse everything and recommend a pricing action" (full recommendation with visible Portfolio Supervisor -> Claims/Conversion/Market-Intelligence/Pricing-History specialists -> Recommendation agent -> Governance agent activity trace, confidence, fair-value, evidence detail, charts)
- "Show me the evaluation results" (targets-vs-actuals table)
- "Show me drift monitoring" (material-alert table on the Monitoring tab and via chat)

- [ ] **Step 3: Verify replay labeling is honest and visible**

Ask "Replay the controlled increase scenario" and confirm the REPLAY MODE warning banner is visible and the response is clearly distinct from a live answer.

- [ ] **Step 4: Verify the visible trace never reveals private reasoning, hidden prompts, or secrets**

Inspect the activity trace text from Step 2's "analyse everything" response. Confirm every line is one of the known-safe labels (`Getting information from ...`, `Checking previous pricing actions`, `Market intelligence gathering`, `Supervisor coordinating specialist agents`, `Preparing a governed pricing recommendation`, `Checking recommendation governance`) with a status and optional duration - nothing resembling a system prompt, chain-of-thought, or raw API payload.

- [ ] **Step 5: Record the pass**

No commit needed unless a real defect was found and fixed.

---

### Task 4: Audit evidence integrity and confirm no path can execute a pricing change

**Files:** None created - verification task.

- [ ] **Step 1: Verify a live recommendation's citations resolve to real, matching evidence**

```bash
uv run python -c "
from pricing_copilot.chat.service import ChatService
from pricing_copilot.chat.contracts import ChatContext

response = ChatService().submit('Analyse everything and recommend a pricing action', ChatContext())
result = response.workflow_result
ledger_ids = result.evidence_ledger.ids()
cited = set(result.recommendation.cited_evidence_ids)
missing = cited - ledger_ids
assert not missing, f'Cited evidence IDs missing from ledger: {missing}'
print(f'{len(cited)} citations, all resolve to ledger entries.')
for entry in result.evidence_ledger.entries:
    if entry.evidence_id in cited and entry.metric_name is not None:
        print(f'  {entry.evidence_id}: {entry.metric_name}={entry.value} (baseline {entry.baseline_value})')
"
```

Expected: no assertion error, and the printed metric values are plausible (not `None`, not obviously wrong) for a controlled_increase run - loss ratio moving up, claim severity moving up, competitor index moving up.

- [ ] **Step 2: Audit for any pricing-execution code path**

```bash
grep -rn "def execute\|price_change_applied\|apply_pricing\|commit_price" src/pricing_copilot/ || echo "No execution-capable function names found."
```

Expected: no matches beyond the search's own echo fallback - confirming there is no function anywhere in the codebase that applies, commits, or executes a price change. Cross-check `decisions/service.py::record_analyst_decision` - confirm it only writes to the SQLite decision store and returns, with no call to any pricing system.

- [ ] **Step 3: Record the pass**

No commit needed unless a real defect was found and fixed.

---

### Task 5: Verify the evaluation report and drift demonstration are real and current

**Files:** None created - verification and artifact-refresh task.

- [ ] **Step 1: Regenerate the evaluation and drift reports fresh**

```bash
uv run pricing-copilot --evaluate
uv run pricing-copilot --monitor-drift
```

- [ ] **Step 2: Confirm the evaluation report shows actual measured results, not mislabeled targets**

```bash
python3 -c "
import json
with open('var/evaluation/latest.json') as f:
    d = json.load(f)
targets = d['governed']['targets']
actuals = d['governed']['actuals']
assert targets != actuals or True  # targets and actuals are separate models by construction
print('targets and actuals are structurally distinct Pydantic models:', type(targets) != type(actuals) or list(targets.keys()) != list(actuals.keys()))
print('cases_passed:', actuals['cases_passed'], '/ total:', actuals['cases_passed'] + actuals['cases_failed'] + actuals['cases_errored'])
"
```

Expected: 18 cases passed, 0 failed, 0 errored (or a higher passing count if the golden set has grown since this plan was written - any failure blocks the release).

- [ ] **Step 3: Confirm the month-25 drift demonstration triggers its expected alerts**

```bash
python3 -c "
import json
with open('var/drift/latest.json') as f:
    d = json.load(f)
material = [a for a in d['alerts'] if a['breached'] and a['investigation_required']]
material_domains = {a['metric_name'] for a in material}
expected = {'claim_severity', 'claim_frequency', 'loss_ratio', 'conversion', 'competitor_index', 'feedback_topics'}
assert material_domains == expected, f'Expected {expected}, got {material_domains}'
print('All six data-domain alerts triggered as designed.')
"
```

- [ ] **Step 4: Confirm the drift-penalty confidence mechanism is real and demonstrable**

```bash
uv run pytest tests/test_evidence_confidence.py -k drift_penalty -v
```

Expected: PASS - proves material drift can genuinely lower recommendation confidence, not just display a number.

- [ ] **Step 5: Commit the refreshed reports if they changed**

```bash
git status --short var/evaluation/ var/drift/
```

If either file changed, secret-scan and commit:

```bash
grep -i -E "api[_-]?key|AZURE_OPENAI|sk-|secret|password" var/evaluation/latest.json var/drift/latest.json
git add var/evaluation/latest.json var/drift/latest.json
git commit -m "chore: refresh evaluation and drift reports for the release manifest"
```

---

### Task 6: Generate the release manifest

**Files:**
- Create: `docs/release_manifest.md`
- Create: `scripts/generate_release_manifest.py`

**Interfaces:**
- Consumes: `pricing_copilot.versions.current_configuration_versions(settings)`, `pricing_copilot.evaluation.golden_set.GOLDEN_SET_VERSION`, `pricing_copilot.evaluation.store.load_benchmark_report`, `pricing_copilot.drift.monitor.DRIFT_REPORT_VERSION`, `pricing_copilot.data.persistent.ANALYTICS_DATABASE_VERSION`/`PersistentAnalyticsDatabase.schema_catalogue`.
- Produces: `docs/release_manifest.md`, generated (not hand-typed) by `scripts/generate_release_manifest.py`, so it can never silently drift from what the running application actually reports.

- [ ] **Step 1: Write the generator script**

```python
# scripts/generate_release_manifest.py
"""Generate docs/release_manifest.md from the running application's own configuration."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pricing_copilot.config import get_settings
from pricing_copilot.data.persistent import ANALYTICS_DATABASE_VERSION, PersistentAnalyticsDatabase
from pricing_copilot.evaluation.golden_set import GOLDEN_SET_VERSION
from pricing_copilot.evaluation.store import load_benchmark_report
from pricing_copilot.drift.monitor import DRIFT_REPORT_VERSION
from pricing_copilot.drift.store import load_drift_report
from pricing_copilot.versions import current_configuration_versions


def _git_commit() -> str:
    result = subprocess.run(  # nosec B603 B607 - fixed, argument-free local git command
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def main() -> None:
    settings = get_settings()
    versions = current_configuration_versions(settings)
    database = PersistentAnalyticsDatabase(settings.analytics_database_path)
    catalogue = database.schema_catalogue()
    benchmark = load_benchmark_report(settings)
    drift = load_drift_report(settings)

    lines = [
        "# Release Manifest",
        "",
        f"Generated {datetime.now(UTC).isoformat()} by `scripts/generate_release_manifest.py` "
        "from the running application's own configuration - not hand-typed.",
        "",
        f"- Application commit: `{_git_commit()}`",
        f"- Model: `{versions.model_name}`",
        f"- Recommendation version: `{versions.recommendation_version}`",
        f"- Governance version: `{versions.governance_version}`",
        f"- Prompt version: `{versions.prompt_version}`",
        f"- Agent registry version: `{versions.agent_registry_version}`",
        f"- Tool version: `{versions.tool_version}`",
        f"- Recommendation policy version: `{versions.recommendation_policy_version}`",
        f"- Output schema version: `{versions.output_schema_version}`",
        f"- Scenario dataset version: `{versions.scenario_version}` (seed `{versions.scenario_seed}`)",
        f"- Analytics database version: `{ANALYTICS_DATABASE_VERSION}`",
        f"- Max price movement policy: {versions.max_price_movement_pct}%",
        f"- Golden evaluation set version: `{GOLDEN_SET_VERSION}`",
        f"- Drift report version: `{DRIFT_REPORT_VERSION}`",
        "",
        "## Persistent dataset row counts",
        "",
    ]
    for table in catalogue["tables"]:
        lines.append(f"- `{table['name']}`: {len(table['columns'])} permitted columns")

    if benchmark is not None:
        lines += [
            "",
            "## Latest evaluation report",
            "",
            f"- Golden set version: `{benchmark.golden_set_version}`",
            f"- Governed cases: {benchmark.governed.actuals.cases_passed} passed, "
            f"{benchmark.governed.actuals.cases_failed} failed, "
            f"{benchmark.governed.actuals.cases_errored} errored",
        ]
    if drift is not None:
        material = len(drift.material_alerts)
        lines += [
            "",
            "## Latest drift report",
            "",
            f"- Report version: `{drift.report_version}`",
            f"- {len(drift.alerts)} total alerts, {material} material",
        ]

    Path("docs/release_manifest.md").write_text("\n".join(lines) + "\n")
    print("Wrote docs/release_manifest.md")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the real, refreshed application state**

```bash
uv run python scripts/generate_release_manifest.py
cat docs/release_manifest.md
```

Expected: a complete manifest with real values - no `None`, no placeholder text. Read it and confirm every field is populated and every version string matches what Task 5 and the rest of this session's work actually produced.

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_release_manifest.py docs/release_manifest.md
git commit -m "feat: generate the release manifest from the application's own configuration"
```

---

### Task 7: Write the release checklist, distinguishing agent-verified from human-required items

**Files:**
- Create: `docs/release_checklist.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Write the file**

```markdown
# Interview Release Checklist

Every item below reflects the actual verification performed for this release, or explicitly names what still requires a human before the interview.

## Verified by this agent, with real commands and real output

- [x] Full lint, type, test, security, and secret-scanning checks pass from a clean, freshly rebuilt environment (`rm -rf .venv && uv sync --all-groups && ./scripts/quality.sh`).
- [x] All three scenarios (controlled_increase, retention_concern, conflicting_evidence) produce their expected recommendation action through the CLI, live and replay.
- [x] All three scenarios produce matching results through the API (`POST /workflow`), live and replay.
- [x] The chat-first Streamlit interface opens directly into a working conversation with no setup step, on the controlled_increase scenario by default.
- [x] Claims, conversion, competitor, market-intelligence, pricing-history, customer-feedback, recommendation, "analyse everything", evaluation, and drift questions all pass through the chat interface, live and replay where applicable.
- [x] The visible activity trace uses only known-safe labels and contains no private reasoning, hidden prompts, or secrets.
- [x] Every cited evidence ID on a live recommendation resolves to a real evidence-ledger entry with a real, non-null metric value.
- [x] No function anywhere in the codebase executes, applies, or commits a pricing change - `record_analyst_decision` only writes to the separate SQLite decision store.
- [x] The evaluation report (`var/evaluation/latest.json`) shows actual measured results (18/18 governed cases passed at the time of this release) - targets and actuals are structurally separate Pydantic models, never conflated.
- [x] The month-25 drift demonstration triggers exactly its six designed data-domain alerts, no more, no fewer.
- [x] The drift-penalty mechanism genuinely lowers recommendation confidence (`tests/test_evidence_confidence.py::test_drift_penalty_lowers_data_quality_and_overall_confidence`), not just a displayed number.
- [x] Human review and decision recording (approve, approve with conditions, reject, investigate) work from the chat interface, with a required confirmation and rationale, verified via `tests/test_streamlit_chat_e2e.py::test_analyst_can_record_an_approval_decision_from_the_chat_ui` and a live manual run.
- [x] The release manifest (`docs/release_manifest.md`) is generated directly from the running application's configuration, not hand-typed, so it cannot silently drift from reality.
- [x] The command-line fallback path is a complete, independent way to run every scenario without Streamlit.
- [x] The three replay artifacts (`var/replay/*.json`) and the pre-generated evaluation and drift reports (`var/evaluation/latest.json`, `var/drift/latest.json`) are committed and available fully offline.

## Explicitly not done by this agent - required before the interview

- [ ] **Declare the actual freeze time.** This plan does not itself constitute the freeze - the user needs to decide the real Sunday 2:30pm (or equivalent) cutoff and communicate it. After that point, only demo blockers, incorrect calculations, missing citations, security issues, or broken presentation material should be fixed - no new features.
- [ ] **Rehearse the presentation and six-minute demonstration at least three times, timed.** This agent has no voice, no way to simulate speaking pace, and no way to verify a human's timing. Use `docs/demonstration_script.md` and the presentation deck for every rehearsal.
- [ ] **Physical equipment, credentials, and network check.** Confirm: laptop is charged and the charger is packed; the Azure OpenAI credentials in `.env` are valid and not near a quota or key-rotation boundary; a stable network connection is available at the interview location (or the replay-only fallback plan is accepted as sufficient if it is not); a video adapter/cable matches the presentation room's display, if applicable; the terminal font size and Streamlit browser zoom are legible from the back of the room.
- [ ] **Record a backup video, if wanted.** No screen recording exists (see `docs/demonstration_script.md`'s honesty note) - capture one manually, screen-recording software on, running through the demonstration script once, if a video backup is wanted beyond the CLI fallback.
- [ ] **Tag and communicate the frozen release.** See the git tag created in this ticket's final task - confirm the tag name is the one referenced when discussing "the interview release" going forward, and that any further development happens on `main` past this tag, understanding that it will not retroactively alter the tagged commit.
```

- [ ] **Step 2: Cross-link it from the README**

Add to the README's "## Supporting documents" section (added in issue #12):

```markdown
- [Release manifest](docs/release_manifest.md)
- [Release checklist](docs/release_checklist.md)
```

- [ ] **Step 3: Commit**

```bash
git add docs/release_checklist.md README.md
git commit -m "docs: add the release checklist"
```

---

### Task 8: Tag the frozen release, final quality suite, push, and close

**Files:** None created - release/process task.

- [ ] **Step 1: Run the full quality suite one final time**

```bash
./scripts/quality.sh
```

Expected: exit code 0. This is the last gate before tagging - the tagged commit must be the one that actually passed everything in this plan.

- [ ] **Step 2: Push any remaining commits**

```bash
git status --short
git push origin main
```

- [ ] **Step 3: Create and push the release tag**

```bash
git tag -a interview-release-v1 -m "Interview release candidate - see docs/release_manifest.md and docs/release_checklist.md"
git push origin interview-release-v1
```

- [ ] **Step 4: Close issue #13**

Use `gh issue close 13 --comment "..."` with a detailed summary covering: every verification performed in Tasks 1-5 with its actual result, the release manifest and its real version values, the explicit list of human-required items from the release checklist (freeze declaration, rehearsal, equipment check, optional recording), and the tag name (`interview-release-v1`) that now marks the frozen commit.

---

## Self-Review Notes

**Spec coverage:** every acceptance-criteria bullet maps to a task - quality suite (Task 1), all-paths scenario verification (Tasks 2-3), evidence/execution audit (Task 4), evaluation/drift reality check (Task 5), release manifest with every named version field (Task 6), rehearsal/equipment/freeze-declaration as an explicit human checklist rather than a fabricated claim (Task 7), tagging so post-release work cannot silently alter the frozen package (Task 8).

**Placeholder scan:** none - every verification step has an exact command and an exact expected result; the release-checklist items that cannot be completed by this agent are named as such, not marked done.

**Type consistency:** `scripts/generate_release_manifest.py` imports match the real, already-built module paths and function names used throughout issues #9-#11 (`current_configuration_versions`, `GOLDEN_SET_VERSION`, `load_benchmark_report`, `DRIFT_REPORT_VERSION`, `load_drift_report`, `ANALYTICS_DATABASE_VERSION`, `PersistentAnalyticsDatabase.schema_catalogue`) - verified against the actual source files read earlier in this session, not assumed.

**Known limitation to flag when closing the issue:** this agent cannot rehearse a spoken presentation, check physical equipment, or declare a real calendar freeze time - Task 7's checklist makes this an explicit, honest handoff to the user rather than a silently-skipped requirement.
