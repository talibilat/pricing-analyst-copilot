# Decision Log

Major product, architecture, policy, testing, and delivery decisions made while building this prototype, in the order they were made.

## Governed multi-agent orchestration over a single large prompt

**Context:** A single LLM call could plausibly produce a pricing recommendation with much less code.
**Decision:** Split the workflow into a Portfolio Supervisor coordinating four evidence specialists (claims, conversion, market intelligence, pricing history), an isolated Recommendation Agent that never sees raw data, and an independent Governance Agent that checks the recommendation against policy.
**Consequence:** More code and more agent calls, but the recommendation step cannot fabricate evidence it never received, and governance runs as a genuinely separate check rather than the same model grading its own work. The single-agent baseline is retained specifically so the golden evaluation benchmark can show this tradeoff with real numbers rather than asserting it.

## Deterministic calculation kept entirely outside the model

**Context:** Loss ratios, movement percentages, and the price-movement clamp are the numbers an analyst will scrutinize hardest.
**Decision:** Every number the recommendation cites is computed by plain Python in `analytics/calculators.py` and clamped by `recommendation/governance.py`, never by the model. The model only narrates already-computed numbers.
**Consequence:** A model hallucination cannot produce a wrong number, only a wrong sentence about a correct number, and the golden evaluation set's deterministic cases (GC-13, GC-14, GC-15) can assert exact values.

## Chat-first interface, not a portfolio-selection form

**Context:** The original prototype shipped a form-based portfolio selector.
**Decision:** The chat-first rebuild made natural-language chat the primary surface; the form is not the primary workflow, and because only one product/region/segment combination is supported, no portfolio-selection UI was added back - scenario and source selection happen through chat keywords and the suggested-questions sidebar instead.
**Consequence:** The interview demo opens directly into a working conversation with zero setup, at the cost of not exercising a portfolio-selection UI pattern that would only matter if more than one portfolio combination existed.

## Replay artifacts as the resilience story, not silent live-to-cache fallback

**Context:** A live Azure OpenAI failure during the interview would be the worst possible failure mode.
**Decision:** When a live run fails, the chat surface reports the failure honestly and offers an explicit "replay the X scenario" action rather than silently substituting cached data (`chat/service.py::_run_pricing_analysis`). Every ChatResponse and WorkflowResult carries a `source: ResultSource` field so replay output is always visibly labeled.
**Consequence:** An analyst, or an interviewer, can never mistake a cached run for a live one, which matters more for trust than a seamless-looking fallback would.

## Golden evaluation set exceeds every stated minimum

**Context:** The spec set minimums of fifteen total cases and two prompt-injection cases.
**Decision:** Built eighteen cases including four prompt-injection or adversarial cases (GC-11, GC-12, GC-16, GC-17) and one multi-turn conversational case (GC-18), rather than stopping at the stated minimums.
**Consequence:** More coverage of the security-critical path than strictly required, at the cost of a slightly larger golden set to maintain; the last live run measured 18/18 passed with zero failures and zero prompt-injection successes.

## Month-25 drift dataset as a new ScenarioName, not an extended existing scenario

**Context:** The drift-monitoring journey needed a reproducible dataset engineered to trigger known drift signals.
**Decision:** Added `ScenarioName.DRIFT_MONITORING` as a fourth, deliberately non-priceable scenario (excluded from `IMPLEMENTED_DATA_SCENARIOS`) rather than extending one of the three existing 24-month scenarios to 25 months.
**Consequence:** Keeps monitoring-only data cleanly separated from priceable scenario data, at the cost of a version bump to `ANALYTICS_DATABASE_VERSION` so existing on-disk databases pick up the new scenario.

## UI end-to-end tests are run through the real Streamlit app, not just the ChatService layer

**Context:** `ChatService`-level tests already covered intent routing, refusals, and evaluation/drift reporting logic in isolation, and appeared to make the interface requirements "done."
**Decision:** Added `streamlit.testing.v1.AppTest`-driven tests that exercise the actual rendered page - clicking through the chat input, checkboxes, and buttons a real analyst would use - rather than trusting that service-layer coverage implies the UI wired it up correctly.
**Consequence:** This surfaced a real, previously undetected bug: the analyst decision-recording form (approve/approve with conditions/reject/investigate) disappeared the moment any widget inside it was touched, because `can_record` was only ever true during the single script run that handled the original chat submission. Any rerun, including the one triggered by ticking the required confirmation checkbox, re-rendered the message from history with `can_record=False` and the form vanished before a decision could ever be submitted. Fixed by keying `can_record` off "is this the most recent message" instead of "was this rendered during the live-submission run." Without UI-level tests this would have shipped broken and only been found live, in the interview.

## Narrow-viewport sidebar clipping found and fixed during accessibility verification

**Context:** The spec requires the interface to be responsive down to narrow layouts and free of clipping.
**Decision:** Manually verified the app at a 375px viewport (both a live resize and a fresh page load) rather than assuming Streamlit's default `initial_sidebar_state="auto"` behaved as documented.
**Consequence:** Found that the sidebar did not auto-collapse and overlapped the main content, clipping the page title and header text. Fixed by setting `initial_sidebar_state="collapsed"` explicitly, trading one extra click to reveal the suggested-questions sidebar on desktop for guaranteed non-clipping at any viewport width.

## Presentation package built as a self-contained HTML deck, not PowerPoint or Google Slides

**Context:** The interview package needs ten main slides plus a technical appendix, with no format mandated.
**Decision:** Built as a single self-contained HTML file, viewable directly in a browser and publishable as a shareable artifact, rather than a PowerPoint or Google Slides file that would require external tooling this agent does not have credentialed access to.
**Consequence:** Fully portable and version-controllable alongside the code, at the cost of not being natively editable in PowerPoint or Keynote if a more conventional format is later wanted for the actual interview.
