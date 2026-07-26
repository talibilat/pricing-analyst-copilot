# Streamlit Chat UI Reskin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing Streamlit chat app (`src/pricing_copilot/streamlit_app.py`) to visually match the Claude Design reference (`Pricing Copilot Chat.dc.html`) — colors, typography, header, empty state, chat bubbles, workflow card — without changing any underlying chat/decision/drift logic.

**Architecture:** A new `streamlit_theme.py` module owns all CSS and small presentational helpers (pill text, avatar data URI, badge/bar HTML snippets). `streamlit_app.py` injects that CSS once, swaps the default title/sidebar for a custom header + empty-state hero, and gets minimal markup edits (avatar params, a couple of `st.markdown(unsafe_allow_html=True)` calls for badges/bars) at existing render call sites. Prompt submission (`chat_input` and suggestion chips) is unified behind one `_submit_prompt()` function so there is still exactly one `st.chat_input` in the tree.

**Tech Stack:** Python 3.12, Streamlit >=1.36, `streamlit.testing.v1.AppTest`, pytest.

## Global Constraints

- Exactly one `st.chat_input` must exist in the rendered app (`len(app.chat_input) == 1`).
- After one exchange, `len(app.chat_message) == 3` (seed assistant + user + assistant reply).
- `len(app.dataframe) == 2` must still hold for a claims-intent query — do not change `_render_table` / `_render_time_series` call structure or count.
- These exact substrings (case-insensitive) must remain in `streamlit_app.py`: `"system recommendation"`, `"analyst decision"` (or `"analyst review"`), `"policy-approved for qualified analyst review"`, `"not a claim of regulatory compliance"`, `"st.chat_message"`, `"st.chat_input"`, `"st.spinner"`, `"activity trace"`. The phrase `"price updated"` (and its banned siblings in `tests/test_streamlit_copy.py`) must never appear.
- No changes to `ChatService`, `chat/contracts.py`, `decisions/`, `drift/`, `evidence/`, or any contract/model — presentation layer only.
- Use `oklch()` color values directly in CSS (matches the source design exactly; no hex conversion).
- Run `pytest tests/test_streamlit_chat_e2e.py tests/test_streamlit_copy.py -v` after every task; both files must stay green throughout.

---

### Task 1: Theme module — CSS and presentational helpers

**Files:**
- Create: `src/pricing_copilot/streamlit_theme.py`
- Test: `tests/test_streamlit_theme.py`

**Interfaces:**
- Produces:
  - `INJECT_CSS: str` — full `<style>...</style>` block, imported and rendered by `streamlit_app.py` via `st.markdown(INJECT_CSS, unsafe_allow_html=True)`.
  - `portfolio_pill_text(question: PortfolioQuestion) -> str` — e.g. `"North West · Personal motor · Renewal · Jul–Dec 2025"`.
  - `assistant_avatar_data_uri() -> str` — `data:image/svg+xml;base64,...` string, a 22x22 rounded "P" badge matching the design's assistant avatar.
  - `confidence_bars_html(items: list[tuple[str, float]]) -> str` — renders the 5-column label/bar/value grid from `(label, fraction_0_to_1)` pairs.
  - `badge_html(label: str, detail: str) -> str` — the green "Proposed: {label}" pill used above the workflow rationale.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_streamlit_theme.py
from datetime import date

from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.streamlit_theme import (
    INJECT_CSS,
    assistant_avatar_data_uri,
    badge_html,
    confidence_bars_html,
    portfolio_pill_text,
)


def test_inject_css_defines_the_reference_palette() -> None:
    assert "<style>" in INJECT_CSS
    assert "oklch(47% 0.085 235)" in INJECT_CSS  # primary blue
    assert "IBM Plex Sans" in INJECT_CSS
    assert "IBM Plex Mono" in INJECT_CSS


def test_portfolio_pill_text_formats_region_product_segment_and_dates() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(
            start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)
        ),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    assert portfolio_pill_text(question) == "North West · Personal motor · Renewal · Jul–Dec 2025"


def test_assistant_avatar_data_uri_is_an_svg_data_uri() -> None:
    uri = assistant_avatar_data_uri()
    assert uri.startswith("data:image/svg+xml;base64,")


def test_confidence_bars_html_renders_one_bar_per_item() -> None:
    html = confidence_bars_html([("Evidence coverage", 0.88), ("Data quality", 0.91)])
    assert html.count("width:88%") == 1
    assert html.count("width:91%") == 1
    assert "Evidence coverage" in html and "Data quality" in html


def test_badge_html_includes_label_and_detail() -> None:
    html = badge_html("Increase", "2% to 3%")
    assert "Proposed: Increase" in html
    assert "2% to 3%" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_streamlit_theme.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.streamlit_theme'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/streamlit_theme.py
from __future__ import annotations

import base64

from pricing_copilot.contracts import PortfolioQuestion

_REGION_LABELS = {"north_west": "North West", "south_east": "South East"}
_PRODUCT_LABELS = {"personal_motor": "Personal motor"}
_SEGMENT_LABELS = {"renewal": "Renewal", "new_business": "New business"}
_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def portfolio_pill_text(question: PortfolioQuestion) -> str:
    period = question.analysis_period
    start = _MONTH_ABBR[period.start_month.month]
    end = _MONTH_ABBR[period.end_month.month]
    if period.start_month.year == period.end_month.year:
        date_range = f"{start}–{end} {period.end_month.year}"
    else:
        date_range = (
            f"{start} {period.start_month.year}–{end} {period.end_month.year}"
        )
    return " · ".join(
        [
            _REGION_LABELS[question.region.value],
            _PRODUCT_LABELS[question.product.value],
            _SEGMENT_LABELS[question.segment.value],
            date_range,
        ]
    )


def assistant_avatar_data_uri() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44">'
        '<rect width="44" height="44" rx="12" fill="oklch(47% 0.085 235)"/>'
        '<text x="22" y="29" font-family="IBM Plex Sans, sans-serif" '
        'font-size="19" font-weight="600" fill="white" '
        'text-anchor="middle">P</text></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def confidence_bars_html(items: list[tuple[str, float]]) -> str:
    cells = []
    for label, fraction in items:
        pct = round(fraction * 100)
        cells.append(
            '<div class="pc-conf-cell">'
            f'<div class="pc-conf-label">{label}</div>'
            '<div class="pc-conf-track">'
            f'<div class="pc-conf-fill" style="width:{pct}%;"></div>'
            "</div>"
            f'<div class="pc-conf-value">{pct}%</div>'
            "</div>"
        )
    return f'<div class="pc-conf-grid">{"".join(cells)}</div>'


def badge_html(label: str, detail: str) -> str:
    return (
        '<div class="pc-workflow-badge-row">'
        f'<span class="pc-badge-action">Proposed: {label}</span>'
        f'<span class="pc-badge-detail">{detail}</span>'
        "</div>"
    )


INJECT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {
  background: oklch(98% 0.012 85);
  font-family: 'IBM Plex Sans', sans-serif;
  color: oklch(22% 0.015 85);
}
[data-testid="stHeader"] { background: transparent; }

.pc-header {
  display:flex; align-items:center; justify-content:space-between; gap:16px;
  padding:12px 4px 20px; border-bottom:1px solid oklch(89% 0.012 85);
}
.pc-header-left { display:flex; align-items:center; gap:12px; }
.pc-logo {
  width:32px; height:32px; border-radius:9px; background:oklch(47% 0.085 235);
  color:white; display:flex; align-items:center; justify-content:center;
  font-weight:600; font-size:15px; flex-shrink:0;
}
.pc-title { font-size:15px; font-weight:600; line-height:1.25; }
.pc-subtitle { font-size:12px; color:oklch(46% 0.014 85); }
.pc-portfolio-pill {
  font-size:12px; font-weight:500; color:oklch(38% 0.02 85);
  background:oklch(94% 0.012 85); border:1px solid oklch(89% 0.012 85);
  border-radius:999px; padding:6px 14px; white-space:nowrap;
}

.pc-empty-state {
  display:flex; flex-direction:column; align-items:center; text-align:center;
  gap:18px; padding-top:8vh;
}
.pc-empty-icon {
  width:44px; height:44px; border-radius:12px; background:oklch(47% 0.085 235);
  color:white; display:flex; align-items:center; justify-content:center;
  font-weight:600; font-size:19px;
}
.pc-empty-heading { font-size:20px; font-weight:600; }
.pc-empty-subtitle {
  font-size:14px; color:oklch(46% 0.014 85); max-width:440px; line-height:1.5;
}
.pc-suggestions .stButton button {
  font-size:13.5px; color:oklch(30% 0.02 85); background:white;
  border:1px solid oklch(88% 0.012 85); border-radius:10px; padding:10px 16px;
  text-align:left; box-shadow:none;
}
.pc-suggestions .stButton button:hover {
  border-color:oklch(47% 0.085 235); color:oklch(38% 0.09 235);
}

[data-testid="stChatMessage"] { gap:9px; }
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {
  border-radius:6px;
}

.pc-copilot-label {
  font-size:11.5px; font-weight:600; letter-spacing:0.04em; text-transform:uppercase;
  color:oklch(50% 0.014 85); margin-bottom:6px;
}

.pc-activity-trace {
  display:flex; flex-direction:column; gap:5px; background:oklch(96% 0.006 85);
  border:1px solid oklch(91% 0.008 85); border-radius:10px; padding:10px 14px;
  font-family:'IBM Plex Mono', monospace; font-size:12px; color:oklch(42% 0.02 85);
}

[data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; }

.pc-workflow-card {
  border:1px solid oklch(89% 0.012 85); border-radius:14px; background:white;
  padding:20px 22px; display:flex; flex-direction:column; gap:16px;
}
.pc-workflow-badge-row { display:flex; align-items:center; gap:10px; }
.pc-badge-action {
  font-size:11.5px; font-weight:700; letter-spacing:0.03em; text-transform:uppercase;
  color:oklch(52% 0.13 150); background:oklch(93% 0.05 150); border-radius:999px;
  padding:5px 12px;
}
.pc-badge-detail { font-size:13.5px; color:oklch(46% 0.014 85); }

.pc-conf-grid { display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; }
.pc-conf-cell { display:flex; flex-direction:column; gap:5px; }
.pc-conf-label { font-size:10.5px; color:oklch(50% 0.014 85); line-height:1.25; height:26px; }
.pc-conf-track { height:5px; border-radius:3px; background:oklch(92% 0.01 85); overflow:hidden; }
.pc-conf-fill { height:100%; border-radius:3px; background:oklch(47% 0.085 235); }
.pc-conf-value { font-size:12px; font-weight:600; }

[data-testid="stExpander"] {
  border:1px solid oklch(89% 0.012 85); border-radius:14px; background:white;
}

[data-testid="stChatInput"] textarea {
  font-family:'IBM Plex Sans', sans-serif; font-size:14.5px;
}
[data-testid="stChatInput"] {
  border-radius:16px !important; border:1px solid oklch(87% 0.012 85) !important;
}

[data-testid="stMetric"] { background:transparent; }
</style>
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_streamlit_theme.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_theme.py tests/test_streamlit_theme.py
git commit -m "feat: add the streamlit chat theme module"
```

---

### Task 2: Inject CSS, add custom header, remove the sidebar

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py:1-30` (imports), `:297-328` (page config, title, sidebar block)
- Test: `tests/test_streamlit_chat_e2e.py` (existing, must stay green), `tests/test_streamlit_copy.py` (existing, must stay green)

**Interfaces:**
- Consumes: `streamlit_theme.INJECT_CSS`, `streamlit_theme.portfolio_pill_text`, `pricing_copilot.contracts.PortfolioQuestion`/`Product`/`Region`/`Segment`/`AnalysisPeriod`.

- [ ] **Step 1: Replace the header block**

In `src/pricing_copilot/streamlit_app.py`, the file already imports `date` (line 4) and has an
existing `from pricing_copilot.contracts import (...)` block (lines 20-25). Add `AnalysisPeriod`,
`PortfolioQuestion`, `Product`, `Region`, `Segment` into that existing block (don't add a second
`contracts` import statement), and add one new import line for the theme module:

```python
from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecisionType,
    DecisionRequest,
    PortfolioQuestion,
    Product,
    Region,
    ResultSource,
    Segment,
    WorkflowResult,
)
from pricing_copilot.streamlit_theme import INJECT_CSS, portfolio_pill_text
```

Then replace lines 297-304 (`st.set_page_config(...)` through the subtitle `st.caption(...)`):

```python
st.set_page_config(
    page_title="Pricing Decision Copilot", layout="wide", initial_sidebar_state="collapsed"
)
st.markdown(INJECT_CSS, unsafe_allow_html=True)

_HEADER_PORTFOLIO = PortfolioQuestion(
    product=Product.PERSONAL_MOTOR,
    region=Region.NORTH_WEST,
    segment=Segment.RENEWAL,
    analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
)
st.markdown(
    f"""
    <div class="pc-header">
      <div class="pc-header-left">
        <div class="pc-logo">P</div>
        <div>
          <div class="pc-title">Pricing Decision Copilot</div>
          <div class="pc-subtitle">Decision support only — never executes a pricing change</div>
        </div>
      </div>
      <div class="pc-portfolio-pill">{portfolio_pill_text(_HEADER_PORTFOLIO)}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
```

Delete the `with st.sidebar:` block (lines 322-328) entirely — there is nothing left to put in it once suggestions move to the empty state in Task 4.

- [ ] **Step 2: Run the existing tests**

Run: `pytest tests/test_streamlit_chat_e2e.py tests/test_streamlit_copy.py -v`
Expected: PASS (still, unchanged) — `"policy-approved for qualified analyst review"`, `"not a claim of regulatory compliance"`, `"system recommendation"`, and `"analyst decision"` are all untouched elsewhere in the file, and `"Decision support only"` is preserved verbatim in the new header markup.

- [ ] **Step 3: Write and run a new sidebar-removed assertion**

Add to `tests/test_streamlit_chat_e2e.py`:

```python
def test_streamlit_app_has_no_sidebar_content() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    assert not app.exception
    assert len(app.sidebar) == 0
```

Run: `pytest tests/test_streamlit_chat_e2e.py::test_streamlit_app_has_no_sidebar_content -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: replace the streamlit title bar with the custom header and drop the sidebar"
```

---

### Task 3: Extract a shared prompt-submission function

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py:330-386` (the `with tab_chat:` block)
- Test: `tests/test_streamlit_chat_e2e.py` (existing `test_streamlit_chat_runs_a_safe_multi_source_query` must keep passing unchanged — this task is a pure refactor)

**Interfaces:**
- Produces: `_submit_prompt(prompt: str) -> None` — module-level function. Appends the user message, runs `ChatService().submit(...)` with the same activity-streaming callback, appends the assistant response, and mirrors current retry-on-replay-failure behavior. Called from both the `st.chat_input` branch and (in Task 4) the suggestion-chip buttons.

- [ ] **Step 1: Write the refactor**

Replace the body of the `with tab_chat:` block (current lines 332-386) with:

```python
def _render_copilot_label() -> None:
    st.markdown('<div class="pc-copilot-label">Copilot</div>', unsafe_allow_html=True)


def _submit_prompt(prompt: str) -> None:
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
    with st.chat_message("assistant", avatar=assistant_avatar_data_uri()):
        _render_copilot_label()
        activity_box = st.empty()
        activity_lines: list[str] = []

        def show_activity(activity: ChatActivity) -> None:
            activity_lines.append(_activity_text(activity))
            activity_box.markdown("  \n".join(activity_lines[-10:]))

        with st.spinner("Working with governed portfolio sources..."):
            response = ChatService().submit(prompt, on_activity=show_activity)
        activity_box.empty()
        if "Live analysis could not complete" in response.message:
            retry_number = len(st.session_state.chat_messages)
            if st.button("Try replay instead", key=f"replay_retry_{retry_number}"):
                retry_context = ChatContext(scenario=response.context.scenario, force_replay=True)
                response = ChatService().submit(prompt, retry_context, on_activity=show_activity)
        if response.activities:
            with st.expander("Activity trace", expanded=True):
                st.write(
                    "\n".join(f"- {_activity_text(activity)}" for activity in response.activities)
                )
        message_number = len(st.session_state.chat_messages)
        _render_response(response, message_number, can_record=True)
    st.session_state.chat_messages.append(
        {"role": "assistant", "response": response.model_dump(mode="json")}
    )


with tab_chat:
    for message_number, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(
            message["role"],
            avatar=assistant_avatar_data_uri() if message["role"] == "assistant" else None,
        ):
            if message["role"] == "assistant":
                _render_copilot_label()
            response = ChatResponse.model_validate(message["response"])
            is_latest_message = message_number == len(st.session_state.chat_messages) - 1
            _render_response(response, message_number, can_record=is_latest_message)

    if prompt := st.chat_input(
        "Ask a portfolio-level pricing question",
        key="pricing_chat_input",
        max_chars=1_000,
        submit_mode="disable",
    ):
        _submit_prompt(prompt)
```

Add the import at the top of the file: `from pricing_copilot.streamlit_theme import assistant_avatar_data_uri, INJECT_CSS, portfolio_pill_text` (merge with the Task 2 import line — keep a single import statement from `pricing_copilot.streamlit_theme`).

Note: this task deliberately renders the "Copilot" label for every historical assistant message too (not just the one just sent) — the design shows it on every assistant turn, and `_render_copilot_label()` is cheap enough to call on each rerun of the message loop.

- [ ] **Step 2: Run the existing e2e test to confirm the refactor is behavior-preserving**

Run: `pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS — `test_streamlit_chat_runs_a_safe_multi_source_query` and `test_replay_keyword_shows_a_prominent_replay_label` both still pass with identical assertions, since `_submit_prompt` produces the same message sequence as the inline code it replaced.

- [ ] **Step 3: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py
git commit -m "refactor: extract _submit_prompt so chat input and suggestion chips share one path"
```

---

### Task 4: Empty-state hero with suggestion chips

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py` (top of the `with tab_chat:` block, before the message loop)
- Test: `tests/test_streamlit_chat_e2e.py`

**Interfaces:**
- Consumes: `_submit_prompt(prompt: str) -> None` from Task 3.
- Produces: no new exports — purely UI wiring inside `streamlit_app.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_streamlit_chat_e2e.py`:

```python
def test_empty_state_shows_suggestion_chips_before_first_exchange() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert len(app.button) == 3
    assert any("recommend a pricing action" in b.label for b in app.button)


def test_clicking_a_suggestion_chip_runs_the_same_exchange_as_typing() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    claims_button = next(b for b in app.button if "claims and conversion" in b.label)
    claims_button.click().run()

    assert not app.exception
    assert len(app.chat_message) == 3
    assert len(app.dataframe) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_streamlit_chat_e2e.py::test_empty_state_shows_suggestion_chips_before_first_exchange -v`
Expected: FAIL — `assert len(app.button) == 3` fails because no suggestion buttons exist yet (0, or 1 if a stray `Try replay instead` button appears — it won't, since no message has been sent).

- [ ] **Step 3: Implement the empty state**

Task 3 left `streamlit_app.py` with a `def _submit_prompt(...): ...` (and `_render_copilot_label`)
followed by a single `with tab_chat:` block containing the message loop and the `st.chat_input`
call. Add a `_SUGGESTIONS` constant above `with tab_chat:`, and add the empty-state block as the
*first* statement inside it, so the complete `with tab_chat:` body becomes:

```python
_SUGGESTIONS = [
    "Show claims and conversion performance",
    "What did competitors do this period?",
    "Analyse everything and recommend a pricing action",
]

with tab_chat:
    if len(st.session_state.chat_messages) == 1:
        st.markdown(
            """
            <div class="pc-empty-state">
              <div class="pc-empty-icon">P</div>
              <div class="pc-empty-heading">What would you like to review?</div>
              <div class="pc-empty-subtitle">Ask about claims, conversion, competitors, pricing
              history, or request a recommendation for this portfolio.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="pc-suggestions">', unsafe_allow_html=True)
        chip_columns = st.columns(len(_SUGGESTIONS))
        clicked_suggestion: str | None = None
        for column, suggestion in zip(chip_columns, _SUGGESTIONS, strict=True):
            if column.button(suggestion, key=f"suggestion_{suggestion}"):
                clicked_suggestion = suggestion
        st.markdown("</div>", unsafe_allow_html=True)
        if clicked_suggestion is not None:
            _submit_prompt(clicked_suggestion)

    for message_number, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(
            message["role"],
            avatar=assistant_avatar_data_uri() if message["role"] == "assistant" else None,
        ):
            if message["role"] == "assistant":
                _render_copilot_label()
            response = ChatResponse.model_validate(message["response"])
            is_latest_message = message_number == len(st.session_state.chat_messages) - 1
            _render_response(response, message_number, can_record=is_latest_message)

    if prompt := st.chat_input(
        "Ask a portfolio-level pricing question",
        key="pricing_chat_input",
        max_chars=1_000,
        submit_mode="disable",
    ):
        _submit_prompt(prompt)
```

There is exactly one `with tab_chat:` block in the file — this listing shows its complete body
(empty state, then message loop, then chat input), replacing what Task 3 left in place.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS (all tests, including the two new ones and the pre-existing `len(app.chat_message) == 3` / `len(app.dataframe) == 2` assertions)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: add the empty-state hero with suggestion chips"
```

---

### Task 5: Workflow card badge and confidence bars

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py:99` and `:116-129` (inside `_render_workflow_result`)
- Test: `tests/test_streamlit_chat_e2e.py`, `tests/test_streamlit_copy.py` (both existing, must stay green)

**Interfaces:**
- Consumes: `streamlit_theme.badge_html(label: str, detail: str) -> str`, `streamlit_theme.confidence_bars_html(items: list[tuple[str, float]]) -> str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_streamlit_chat_e2e.py`:

```python
def test_workflow_result_renders_a_proposed_action_badge() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Analyse everything and recommend a pricing action")
    app.run()

    assert not app.exception
    markdown_html = "\n".join(item.value for item in app.markdown)
    assert "pc-badge-action" in markdown_html
    assert "Proposed:" in markdown_html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_streamlit_chat_e2e.py::test_workflow_result_renders_a_proposed_action_badge -v`
Expected: FAIL — no `pc-badge-action` markup exists yet.

- [ ] **Step 3: Wire the badge and confidence bars into `_render_workflow_result`**

Replace line 99 (`st.markdown(f"**Proposed action:** {action}")`) with:

```python
    st.markdown(badge_html(recommendation.action.value, action), unsafe_allow_html=True)
```

Replace lines 116-129 (the `if recommendation.confidence is not None:` block) with:

```python
    if recommendation.confidence is not None:
        confidence = recommendation.confidence
        st.markdown("**Confidence**")
        st.markdown(
            confidence_bars_html(
                [
                    ("Evidence coverage", confidence.evidence_coverage),
                    ("Source freshness", confidence.source_freshness),
                    ("Specialist agreement", confidence.specialist_agreement),
                    ("Data quality", confidence.data_quality),
                    ("Conflict penalty", confidence.conflict_penalty),
                ]
            ),
            unsafe_allow_html=True,
        )
        st.caption(f"Overall confidence: {confidence.overall * 100:.0f}%")
```

Add the import: `from pricing_copilot.streamlit_theme import badge_html, confidence_bars_html` (merge into the existing `streamlit_theme` import line from Tasks 2-3).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_streamlit_chat_e2e.py tests/test_streamlit_copy.py -v`
Expected: PASS (all tests — the copy test still finds `"system recommendation"` and the policy phrases, which live in the untouched `st.caption` call three lines above line 99).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: restyle the workflow card's proposed-action badge and confidence bars"
```

---

### Task 6: CSS-only pass over expanders, tables, and the Monitoring tab

**Files:**
- Modify: `src/pricing_copilot/streamlit_theme.py` (extend `INJECT_CSS` only — no new Python logic)
- Test: `tests/test_streamlit_theme.py`, `tests/test_streamlit_chat_e2e.py`, `tests/test_streamlit_copy.py` (all existing, must stay green — this task adds no new Python call sites in `streamlit_app.py`)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — extends the existing `INJECT_CSS` string constant.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_streamlit_theme.py`:

```python
def test_inject_css_styles_monitoring_alert_expanders() -> None:
    assert '[data-testid="stExpander"]' in INJECT_CSS
    assert "pc-conf-grid" in INJECT_CSS
```

Run: `pytest tests/test_streamlit_theme.py::test_inject_css_styles_monitoring_alert_expanders -v`
Expected: PASS already (both selectors were added in Task 1) — this step confirms the baseline before extending the CSS further; proceed to Step 2 to add the remaining rules below.

- [ ] **Step 2: Extend `INJECT_CSS`**

Append to the `INJECT_CSS` string in `src/pricing_copilot/streamlit_theme.py`, just before the closing `</style>`:

```css
[data-testid="stExpander"] summary {
  font-size:13.5px; font-weight:500; padding:12px 2px;
}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] { padding:4px 18px 16px; }

.pc-evidence-entry {
  border-bottom:1px solid oklch(94% 0.008 85); padding-bottom:12px; margin-bottom:12px;
}

[data-testid="stTabs"] button[data-baseweb="tab"] {
  font-family:'IBM Plex Sans', sans-serif; font-size:13.5px; font-weight:500;
}

.pc-monitoring-status-ok { color:oklch(52% 0.13 150); font-weight:600; }
.pc-monitoring-status-warn { color:oklch(55% 0.13 70); font-weight:600; }
.pc-monitoring-status-error { color:oklch(55% 0.18 25); font-weight:600; }
```

- [ ] **Step 3: Run the full theme and app test suites**

Run: `pytest tests/test_streamlit_theme.py tests/test_streamlit_chat_e2e.py tests/test_streamlit_copy.py -v`
Expected: PASS (all tests)

- [ ] **Step 4: Commit**

```bash
git add src/pricing_copilot/streamlit_theme.py tests/test_streamlit_theme.py
git commit -m "style: extend theme CSS to cover expanders, tabs, and monitoring status text"
```

---

### Task 7: Full test suite, manual browser verification, and known-gaps note

**Files:**
- None modified — verification only. May touch `src/pricing_copilot/streamlit_theme.py` / `src/pricing_copilot/streamlit_app.py` if the browser check surfaces a selector mismatch against the installed Streamlit version's `data-testid` attributes.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS — every test, not just the Streamlit ones (Task 5/6 changes are presentation-only and shouldn't affect `chat/service.py`, `decisions/`, `drift/`, or any other module's tests).

- [ ] **Step 2: Launch the app and verify visually**

Run: `streamlit run src/pricing_copilot/streamlit_app.py`

Using the browser preview tool, verify in order:
1. Header shows the "P" logo badge, title, subtitle, and portfolio pill (no default `st.title`/sidebar visible).
2. Empty state shows the hero icon, heading, subtitle, and three suggestion chips.
3. Clicking a chip runs the same exchange as typing it — activity trace streams, then the response renders.
4. The workflow-triggering prompt ("Analyse everything and recommend a pricing action") shows the green "Proposed:" badge and the 5-bar confidence grid.
5. Evidence detail, Supporting charts, and Confirm-and-record-a-decision expanders open/close and the decision form submits successfully.
6. Switch to the Monitoring tab — fonts/colors are consistent with the Chat tab.

If any `data-testid` selector in `INJECT_CSS` doesn't match what the installed Streamlit version renders (inspect via the browser tool's `read_page` or dev-tools element inspector), update the selector in `streamlit_theme.py` and re-run `pytest tests/test_streamlit_theme.py -v` plus a fresh visual check.

- [ ] **Step 3: Take a confirmation screenshot**

Use `computer {action: "screenshot"}` on the running preview and share it as proof the reskin matches the reference design's layout and palette.

- [ ] **Step 4: Commit any selector fixes from Step 2, if needed**

```bash
git add src/pricing_copilot/streamlit_theme.py
git commit -m "fix: correct streamlit data-testid selectors found during manual verification"
```

(Skip this step if Step 2 required no changes.)
