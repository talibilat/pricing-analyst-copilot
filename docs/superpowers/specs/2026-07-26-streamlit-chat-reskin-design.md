# Streamlit chat UI reskin — design

## Context

A visual reference for the pricing chat UI was authored in Claude Design as
`Pricing Copilot Chat.dc.html`, a `.dc` component rendered by a React-based
runtime (`support.js`, from `dc-runtime`).
It is a live, client-side React app: template directives (`x-dc`, `sc-if`,
`sc-for`), a component class with `state`/`setState`, `onClick`/`onChange`
handlers, and CSS `@keyframes` animations.

Streamlit is a server-driven, rerun-on-interaction Python framework.
It has no client-side JS runtime and cannot execute the `.dc` component or
`support.js` as-is.
The user chose a Streamlit CSS/layout reskin of the existing app
([streamlit_app.py](../../../src/pricing_copilot/streamlit_app.py)) over a
from-scratch React port, accepting that some interaction fidelity
(staggered animations, flicker-free collapse, the exact composite input bar)
will be approximated rather than exact.

The existing Streamlit app already implements the same functional pieces the
design shows: chat bubbles, a real-time activity trace (streamed via
`ChatService.submit(..., on_activity=...)`, not simulated), an evidence
expander, supporting charts, and an analyst-decision form.
This is a presentation-layer change only — no changes to `ChatService`,
`decisions/`, `drift/`, or any contract/model.

## Constraints from existing tests

`tests/test_streamlit_chat_e2e.py` and `tests/test_streamlit_copy.py` must
keep passing unmodified:

- Exactly one `st.chat_input` must exist (`len(app.chat_input) == 1`).
  Suggestion chips must reuse the same submit path as the chat input, not
  add a second input.
- After one exchange, `len(app.chat_message) == 3` (seed assistant message +
  user + assistant reply). The seed message must still be rendered as a
  `st.chat_message` once a real exchange has happened.
- `len(app.dataframe) == 2` for the claims-intent query — no change to
  `_render_table` / `_render_time_series` call structure.
- The activity-trace text asserted via `app.markdown` must still be produced
  through `st.markdown` calls with the same text (`_activity_text`).
- These exact source substrings (case-insensitive) must remain in
  `streamlit_app.py`: `"price updated"` etc. must stay *absent*;
  `"system recommendation"`, `"analyst decision"` (or `"analyst review"`),
  `"policy-approved for qualified analyst review"`,
  `"not a claim of regulatory compliance"`, `"st.chat_message"`,
  `"st.chat_input"`, `"st.spinner"`, `"activity trace"` must stay *present*.

## Visual system

- Google Fonts import (IBM Plex Sans body / IBM Plex Mono for
  activity/citation text) and the design's exact `oklch()` colors, injected
  once via a `<style>` block (`st.markdown(unsafe_allow_html=True)`).
  `oklch()` is used directly rather than converted to hex — modern evergreen
  browsers support it natively, and it keeps the palette pixel-identical to
  the source design rather than introducing rounding error.
- New module `src/pricing_copilot/streamlit_theme.py`: holds the CSS string
  and small HTML-snippet builders (header bar, portfolio pill, suggestion
  chip, badge). Keeps `streamlit_app.py` from growing into a style dump.

## Layout changes

- **Header**: replace `st.title` / `st.caption` with a custom header bar —
  "P" logo badge, "Pricing Decision Copilot" title, the existing subtitle
  copy (kept verbatim for the copy test), and a portfolio pill. The pill
  text is derived from the actual default `PortfolioQuestion` fields (not
  hardcoded), so it can't drift from real config.
- **Sidebar**: remove the "Suggested questions" list. `initial_sidebar_state`
  stays `"collapsed"`; if nothing else ever populates the sidebar, the
  `with st.sidebar:` block is deleted outright.
- **Empty state**: shown only while `st.session_state.chat_messages` still
  has just the seed assistant message and no real exchange has occurred yet.
  Renders the hero icon, "What would you like to review?", subtitle copy,
  and three suggestion chips. Chips are `st.button`s that call the same
  `_submit_prompt(text)` function used by `st.chat_input`, so behavior is
  identical to typing the suggestion. Once any real message exists, this
  hero is not shown again and the seed message renders as a normal
  `st.chat_message` bubble (satisfies the `len(app.chat_message) == 3`
  assertion).
- **Chat bubbles**: user bubble right-aligned/rounded per the design;
  assistant messages get a small "P" badge avatar via `st.chat_message`'s
  `avatar=` parameter (inline SVG data URI) plus the uppercase "COPILOT"
  label.
- **Workflow card**: restyle the existing recommendation rendering
  (`_render_workflow_result`) into the bordered card layout — proposed
  action badge, rationale, counter-evidence callout, confidence bars (reuse
  `st.columns`/`st.metric`, restyled), citation chips — without changing
  what data feeds it.
- **Expanders** (evidence detail, supporting charts, decision form): kept as
  `st.expander`, restyled via CSS to look like the design's flat
  section-toggle rows rather than Streamlit's default boxed expander chrome.
- **Chat input**: CSS-restyled `st.chat_input` (rounded pill, closer
  placement) — not a pixel-exact rebuild of the composite
  textarea+circular-button control from the design; documented gap.
- **Monitoring tab**: same fonts/colors/card CSS applied for visual
  consistency, extrapolated since the reference design doesn't cover it.

## Known gaps vs. the reference (accepted, not silently dropped)

- No staggered fade-in animation on activity-trace lines (Streamlit rerun
  model doesn't support it without a custom bidirectional component).
- No flicker-free client-side expand/collapse — toggling an expander causes
  a script rerun, not a smooth in-place transition.
- Chat input is an approximation, not the exact composite control.

## Testing

- `tests/test_streamlit_chat_e2e.py` and `tests/test_streamlit_copy.py` pass
  unmodified.
- Manual verification via browser preview: empty state → suggestion chip
  click → real chat exchange → expand evidence/charts/decision sections →
  record a decision → switch to Monitoring tab. Check light-mode rendering
  (the design is a fixed light palette, not tied to Streamlit's theme
  toggle).
