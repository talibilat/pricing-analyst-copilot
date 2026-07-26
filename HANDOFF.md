# Handoff: Streamlit chat UI reskin (pricing-analyst-copilot)

## Goal

Restyle the existing Streamlit chat app (`src/pricing_copilot/streamlit_app.py`) to
visually match a Claude Design reference (`Pricing Copilot Chat.dc.html`, a React
`.dc` component that cannot run inside Streamlit as-is) — colors, typography, header,
empty state, chat bubbles, workflow card — **without changing any underlying
chat/decision/drift business logic**. This is a presentation-layer-only change.

The user was asked "Streamlit or React?" up front; they chose a Streamlit CSS/layout
reskin of the existing app over a React rebuild, accepting some fidelity gaps
(no staggered activity-trace animation, no flicker-free expand/collapse, the input
bar is an approximation).

## Where everything lives

- **Design analysis / source of truth for the visual reference:** already fully
  extracted and distilled — you do not need to re-fetch it. See
  `docs/superpowers/specs/2026-07-26-streamlit-chat-reskin-design.md` for the
  design decisions and known gaps.
- **Implementation plan (the primary document — read this directly, it has
  complete, exact code for every remaining task):**
  `docs/superpowers/plans/2026-07-26-streamlit-chat-reskin.md`. 7 tasks. Its
  "Global Constraints" section documents the 10 pre-existing test failures you'll
  see in this repo (see below) — read that section before touching tests.
- **Worktree:** `.worktrees/streamlit-chat-reskin` (gitignored, isolated from the
  main checkout), branch `streamlit-chat-reskin`, branched off
  `codex/complete-system-documentation` (itself off `main`). All work should
  continue in this worktree.
- **Progress ledger:** `.worktrees/streamlit-chat-reskin/.superpowers/sdd/progress.md`
  — one line per completed task with commit ranges.

## Current state

Working via Anthropic's `subagent-driven-development` process (implementer subagent
→ task reviewer subagent → fix loop, per task). This was interrupted by the user
mid-Task-4 to request this handoff instead — nothing is blocked, just paused.

**Completed and committed** (worktree HEAD is `276f008`):
- Task 1 — `src/pricing_copilot/streamlit_theme.py` + `tests/test_streamlit_theme.py`:
  CSS (`INJECT_CSS`, uses `oklch()` colors directly, no hex conversion) and
  presentational helpers (`portfolio_pill_text`, `assistant_avatar_data_uri`,
  `confidence_bars_html`, `badge_html`). Commits `8b6f31a..37fb79a`.
- Task 2 — custom header bar (logo badge, title, subtitle, portfolio pill) replacing
  `st.title`/`st.caption`; sidebar removed entirely. Commits `37fb79a..0f95609`.
- Task 3 — extracted `_submit_prompt(prompt: str) -> None` and
  `_render_copilot_label()` so chat-input submission and (planned) suggestion-chip
  clicks share one code path. Pure refactor, reviewer-approved with zero findings.
  Commits `0f95609..276f008`.

Each task went through implementer → reviewer → (fix if needed) → re-review before
being marked done; see the ledger file for exact commit ranges and what each fix
addressed.

**In progress, UNCOMMITTED, and currently broken** — Task 4 (empty-state hero +
suggestion chips):
- `src/pricing_copilot/streamlit_app.py` and `tests/test_streamlit_chat_e2e.py` have
  uncommitted changes matching the plan's Task 4 code almost exactly (empty-state
  hero markup, 3 suggestion-chip buttons, two new tests).
- **Known bug, root-caused, not yet fixed:** clicking a suggestion chip produces
  5 chat messages instead of 3
  (`test_clicking_a_suggestion_chip_runs_the_same_exchange_as_typing` fails on
  `assert len(app.chat_message) == 3`, actual is 5). Cause: the plan's Task 4 code
  calls `_submit_prompt(clicked_suggestion)` **before** the `for message_number,
  message in enumerate(st.session_state.chat_messages):` history loop, in the same
  script pass. `_submit_prompt` both (a) renders the new user+assistant bubbles
  directly via `st.chat_message(...)`, and (b) appends them to
  `st.session_state.chat_messages`. Because this happens before the history loop
  runs in the *same* execution, the loop then re-renders those same two just-appended
  messages a second time. The existing `st.chat_input` path never hit this because
  it's called *after* the history loop (mirroring the plan's own working code). The
  other new test (`test_empty_state_shows_suggestion_chips_before_first_exchange`)
  passes fine.
  - **Fix direction (not yet implemented):** don't call `_submit_prompt` from inside
    the empty-state block before the loop. Instead, capture `clicked_suggestion`
    there, then call `_submit_prompt` once, after the history loop, alongside (or
    instead of) the `st.chat_input` branch — e.g. `submitted = clicked_suggestion or
    st.chat_input(...)` evaluated after the loop, then a single
    `if submitted: _submit_prompt(submitted)`. This matches the existing working
    call site for `st.chat_input` and avoids the double-render. Whoever picks this
    up should fix this, update the plan's Task 4 code block for the record, then
    finish Task 4 with TDD (both new tests green), get it reviewed, and commit.
- Do not commit this WIP as-is — it has the bug above.

## Decisions made (don't re-litigate)

- Streamlit reskin, not React — user's explicit choice after being shown the
  tradeoffs.
- Match the design's layout: sidebar's old "Suggested questions" list removed
  entirely, replaced by empty-state chips; custom header bar instead of
  `st.title`/`st.caption`.
- Also restyle the Monitoring tab (Task 6) for visual consistency even though it has
  no reference mockup — extrapolate from the chat design's visual language.
- Use `oklch()` CSS colors directly (matches the source design exactly; modern
  browsers support it; no hex conversion).
- The header's portfolio pill text is derived from the **actual** default
  `PortfolioQuestion` used by `chat/service.py` (`Jul–Dec 2025`), not the design
  mockup's fictional `Jan–Jun 2026` — avoids drifting from real app config.
- Used a manual `git worktree add` (not the native `EnterWorktree` tool) because
  `EnterWorktree`'s default `baseRef` branches fresh off `origin/main`, which would
  have dropped the plan/spec commits already made on the local feature branch.
  `.worktrees/` and `.superpowers/` are both gitignored.

## What failed / dead ends (don't repeat these)

- **The plan's original Task 5 test used a live "Analyse everything and recommend a
  pricing action" prompt.** This can never pass in this environment —
  `.env` has `AZURE_OPENAI_API_KEY=` / `AZURE_OPENAI_ENDPOINT=` present but **empty**
  (no real credentials exist anywhere, this isn't a sandbox/network issue). Already
  fixed: the plan file's Task 5 now uses the deterministic replay-artifact pattern
  (`save_replay_artifact` + `PRICING_COPILOT_REPLAY_DIRECTORY` monkeypatch), same
  approach as the existing `test_replay_keyword_shows_a_prominent_replay_label`.
  This fix is already baked into the plan — just follow it as written.
- **`get_settings()` is `@lru_cache`d** (`src/pricing_copilot/config.py:97`) — a
  pre-existing, out-of-scope bug. Confirmed (checked out the pre-Task-3 commit and
  reproduced identically) that running
  `test_streamlit_chat_runs_a_safe_multi_source_query` and
  `test_replay_keyword_shows_a_prominent_replay_label` **together** in one pytest
  invocation fails the replay test even though each passes alone — true both before
  and after every task's diff so far. Don't try to fix this; it's out of scope. The
  plan's Global Constraints section lists all 10 pre-existing failing tests
  (confirmed via a full `pytest -v` baseline run before Task 1 started) — treat "no
  regressions" as "the failure set doesn't grow," not "zero failures."
- **The worktree's `.venv` broke once** (editable-install `.pth` pointed at the right
  path but Python wasn't picking it up — `import pricing_copilot` failed everywhere
  including plain `pytest`). Root cause unconfirmed (possibly a `uv sync` timing
  quirk), but the fix was simple and worked: `rm -rf .venv && uv sync --frozen`. If
  you hit `ModuleNotFoundError: No module named 'pricing_copilot'` in this worktree,
  do that first before assuming a code problem. Also note: `.env` (Azure OpenAI
  settings, all blank) is gitignored and was manually copied from the main checkout
  into this worktree — if you ever recreate the worktree from scratch, copy it again
  or tests requiring `get_settings()` will differ subtly (though not in a way that
  changes the pass/fail set, since credentials are blank either way).

## Next steps (priority order)

1. Fix the Task 4 double-render bug (see above), finish Task 4 with TDD, get both
   new tests green, commit.
2. Task 5 — workflow card badge + confidence bars. Plan already has the corrected,
   deterministic replay-artifact-based test. Straightforward transcription of the
   plan's code.
3. Task 6 — CSS-only pass over expanders/tables/Monitoring tab (extends
   `INJECT_CSS`, no Python logic changes).
4. Task 7 — full test suite run + manual browser verification (`streamlit run
   src/pricing_copilot/streamlit_app.py`, click through empty state → chip → real
   exchange → expand evidence/charts/decision → record a decision → Monitoring tab)
   + a confirmation screenshot.
5. Final whole-branch code review (dispatch on the most capable available model per
   `subagent-driven-development`'s guidance), then decide merge/PR via
   `finishing-a-development-branch`.

If continuing with the same subagent-driven-development process: the ledger file
already has Tasks 1-3 marked complete — do not re-dispatch them. Resume at Task 4.
Task 4's brief was already extracted to
`.worktrees/streamlit-chat-reskin/.superpowers/sdd/task-4-brief.md` if it still
exists (regenerate with the plan's `scripts/task-brief` if not).

## Design details worth knowing

- Source design: Claude Design project "Frontend redesign for chat UI"
  (`projectId 87d856f5-78f5-413b-ba5c-9e57352656d8`), file
  `Pricing Copilot Chat.dc.html` + `support.js`. Already fully read and distilled —
  no need to re-fetch via the design MCP unless you want to double check a specific
  pixel value not captured in the spec/plan.
- Visual system: IBM Plex Sans (body) / IBM Plex Mono (activity trace, citations),
  `oklch()` color palette, defined once in `streamlit_theme.INJECT_CSS`.
- The plan file is the single most useful artifact for implementation — every
  remaining task (4-7) has complete, ready-to-transcribe Python/CSS/test code, not
  just prose descriptions.

## Suggested skills

- `superpowers:subagent-driven-development` — to continue exactly as before
  (implementer subagent → task reviewer subagent → fix loop, per task), if picking
  this up as a fresh session in the same style.
- `superpowers:executing-plans` — alternative if picking this up as a parallel/human
  -reviewed session instead.
- `superpowers:finishing-a-development-branch` — once Task 7 and the final
  whole-branch review are done.
