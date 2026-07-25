# Interview Release Checklist

Every item below reflects the actual verification performed for this release, or explicitly names what still requires a human before the interview.

## Verified by this agent, with real commands and real output

- [x] Full lint, type, test, security, and secret-scanning checks pass from a clean, freshly rebuilt environment (`rm -rf .venv && uv sync --all-groups && ./scripts/quality.sh`).
- [x] All three scenarios (controlled_increase, retention_concern, conflicting_evidence) produce their expected recommendation action (increase, decrease, investigate) through the CLI, live and replay.
- [x] All three scenarios produce matching results through the API (`POST /workflow`), live and replay.
- [x] The chat-first Streamlit interface opens directly into a working conversation with no setup step, on the controlled_increase scenario by default.
- [x] Claims, conversion, competitor, market-intelligence, pricing-history, customer-feedback, recommendation, "analyse everything", evaluation, and drift questions all pass through the chat interface, live and replay where applicable.
- [x] Scenario switching by keyword works from chat (asking about "the retention concern scenario" correctly retrieves retention_concern data).
- [x] An out-of-scope request for customer-level personal data is refused in the chat interface with a clear, honest explanation.
- [x] The visible activity trace uses only known-safe labels (Getting information from X, Checking previous pricing actions, Market intelligence gathering, Supervisor coordinating specialist agents, Preparing a governed pricing recommendation, Checking recommendation governance) and contains no private reasoning, hidden prompts, or secrets.
- [x] The Portfolio Supervisor and all four named specialist agents (claims, conversion, market intelligence, pricing history), the recommendation agent, and the governance agent are all visibly represented in a live "analyse everything" trace.
- [x] Every cited evidence ID on a live recommendation resolves to a real evidence-ledger entry with a real, non-null metric value.
- [x] No function anywhere in the codebase executes, applies, or commits a pricing change - `execute_plan` is a read-only DuckDB query executor (`read_only=True`, allowlisted `SELECT` only) and `record_analyst_decision` only writes to the separate, append-only SQLite decision store.
- [x] The evaluation report (`var/evaluation/latest.json`) shows actual measured results (18/18 governed cases passed at the time of this release) - targets and actuals are structurally separate Pydantic models, never conflated.
- [x] The month-25 drift demonstration triggers exactly its six designed data-domain alerts (claim severity, claim frequency, loss ratio, conversion, competitor index, feedback topics), no more, no fewer.
- [x] The drift-penalty mechanism genuinely lowers recommendation confidence (`tests/test_evidence_confidence.py::test_drift_penalty_lowers_data_quality_and_overall_confidence`), not just a displayed number.
- [x] Human review and decision recording work from the chat interface, with a required confirmation and rationale, verified via `tests/test_streamlit_chat_e2e.py::test_analyst_can_record_an_approval_decision_from_the_chat_ui`.
- [x] The release manifest (`docs/release_manifest.md`) is generated directly from the running application's configuration, including real DuckDB row counts, not hand-typed, so it cannot silently drift from reality.
- [x] The command-line fallback path is a complete, independent way to run every scenario without Streamlit.
- [x] The three replay artifacts (`var/replay/*.json`) and the pre-generated evaluation and drift reports (`var/evaluation/latest.json`, `var/drift/latest.json`) are committed and available fully offline.

## Explicitly not done by this agent - required before the interview

- [ ] **Declare the actual freeze time.** This checklist does not itself constitute the freeze - the user needs to decide the real cutoff and communicate it. After that point, only demo blockers, incorrect calculations, missing citations, security issues, or broken presentation material should be fixed - no new features.
- [ ] **Rehearse the presentation and six-minute demonstration at least three times, timed.** This agent has no voice, no way to simulate speaking pace, and no way to verify a human's timing. Use `docs/demonstration_script.md` and the presentation deck for every rehearsal.
- [ ] **Physical equipment, credentials, and network check.** Confirm: laptop is charged and the charger is packed; the Azure OpenAI credentials in `.env` are valid and not near a quota or key-rotation boundary; a stable network connection is available at the interview location (or the replay-only fallback plan is accepted as sufficient if it is not); a video adapter/cable matches the presentation room's display, if applicable; the terminal font size and Streamlit browser zoom are legible from the back of the room.
- [ ] **Record a backup video, if wanted.** No screen recording exists (see `docs/demonstration_script.md`'s honesty note) - capture one manually, screen-recording software on, running through the demonstration script once, if a video backup is wanted beyond the CLI fallback.
- [ ] **Tag and communicate the frozen release.** This ticket tags the current commit as `interview-release-v1` - confirm this is the tag referenced when discussing "the interview release" going forward, and that any further development happens on `main` past this tag, understanding that it will not retroactively alter the tagged commit.
