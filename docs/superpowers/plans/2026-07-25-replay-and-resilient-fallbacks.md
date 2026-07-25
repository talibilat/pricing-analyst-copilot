# Transparent Replay and Resilient Demonstration Fallbacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every supported scenario a validated, version-checked replay artifact that can stand in for a live model call - through the same typed contracts used live - so the chat, API, and CLI interfaces stay usable and honest when a live call is slow, unavailable, or invalid, without ever silently presenting cached output as live.

**Architecture:** A new `replay` package stores one JSON artifact per scenario, each wrapping a full `ChatResponse` (which itself nests the complete `WorkflowResult`) plus the exact `ConfigurationVersions` that produced it. Loading an artifact re-validates every version field against the running configuration and refuses stale artifacts. The live governed pipeline gets one small hardening fix - a missing-credentials/unavailable-model failure becomes a safe, clearly-worded `investigate` outcome instead of an uncaught exception, using the same `"workflow: ..."` failure-reason prefix convention the timeout and generic-exception paths already use. Chat, API, and CLI each gain an explicit, opt-in replay path (a keyword, a context flag, and a CLI flag respectively) - never an automatic silent fallback - and the interface adds a prominent, impossible-to-miss replay label plus an explicit "try replay instead" affordance that fires only after a detected live failure, preserving the original question.

**Tech Stack:** Same as the rest of the repository - Python 3.12, Pydantic v2, `openai-agents`, FastAPI, Streamlit (`streamlit.testing.v1.AppTest` for interface-level tests - this harness drives the chat interface directly in-process and avoids the browser-automation friction hit with the old form-based BaseWeb selects), pytest, Ruff, MyPy, Bandit.

## Global Constraints

- Replay is always an explicit choice (a chat keyword, a `ChatContext.force_replay` flag, or a CLI `--replay` flag) - never an automatic fallback from a live failure.
- A replay artifact that doesn't match the *current* `ConfigurationVersions` (model, prompt, agent registry, tool, dataset, policy, output-schema versions) is rejected, not silently served.
- Replayed output uses the exact same typed contracts (`WorkflowResult`, `ChatResponse`) as live output - no parallel "replay shape."
- The interface must prominently label replay output and never render it indistinguishably from a live call.
- Replaying an analysis is read-only - it must never call `record_analyst_decision` or otherwise write a decision record itself.
- `AnalystDecision`/`DecisionRequest` carry a `source` field so a recorded decision's live-vs-replay origin is preserved permanently.
- The existing bounded-retry/timeout machinery in `orchestration/runtime.py` and `orchestration/pipeline.py::_run_and_close_client` (max one retry, tool/request/workflow timeouts, safe-failure catch-all) is the established pattern for "produce a clear user-facing state" - extend it, don't replace it.
- Every new or changed public contract field gets a sensible default so existing callers, fixtures, and stored JSON keep working without modification.

---

## File Structure

- Create: `src/pricing_copilot/versions.py` - single source of truth for `ConfigurationVersions`, extracted from the two places that currently build it by hand.
- Create: `src/pricing_copilot/replay/__init__.py`, `src/pricing_copilot/replay/contracts.py`, `src/pricing_copilot/replay/store.py` - the replay artifact contract, save/load, and version-compatibility validation.
- Create: `src/pricing_copilot/replay/pipeline.py` - `run_replay_portfolio_workflow`.
- Create: `var/replay/controlled_increase.json`, `var/replay/retention_concern.json`, `var/replay/conflicting_evidence.json` - the three real, live-recorded replay artifacts (generated and committed in Task 10).
- Modify: `src/pricing_copilot/contracts.py` - add `ResultSource` enum, `ConfigurationVersions.output_schema_version`, `WorkflowResult.source`, `DecisionRequest.source`, `AnalystDecision.source`.
- Modify: `src/pricing_copilot/chat/contracts.py` - add `ChatIntent.REPLAY`, `ChatContext.force_replay`, `ChatResponse.source`.
- Modify: `src/pricing_copilot/chat/service.py` - remove "replay" from the evaluation-intent keywords, add replay intent handling, detect a live workflow-level failure and offer an explicit replay choice instead of silently doing anything.
- Modify: `src/pricing_copilot/orchestration/pipeline.py` - safe-fail the missing-credentials case; use `versions.py` instead of its own `_configuration_versions`.
- Modify: `src/pricing_copilot/decisions/service.py` - use `versions.py`; propagate `source`.
- Modify: `src/pricing_copilot/workflow.py` - add `replay: bool = False` kwarg to `run_portfolio_workflow`.
- Modify: `src/pricing_copilot/config.py` - add `replay_directory: Path = Path("var/replay")`.
- Modify: `src/pricing_copilot/api.py` - `replay` query parameter on `POST /workflow`.
- Modify: `src/pricing_copilot/cli.py` - `--replay`, `--json`, `--record-replay-artifacts` flags; human-readable summary as the default output.
- Modify: `src/pricing_copilot/streamlit_app.py` - prominent replay banner; a "Try replay instead" button after a detected live failure.
- Modify: `.gitignore` - carve out `var/replay/*.json` from whatever currently ignores `var/` (the three artifacts must be committed).
- Test: `tests/test_versions.py`, `tests/test_replay_store.py`, `tests/test_replay_pipeline.py`, `tests/test_orchestration_pipeline.py` (extend), `tests/test_chat_service.py` (extend), `tests/test_cli.py` (extend), `tests/test_api.py` (extend), `tests/test_decisions_service.py` (extend), `tests/test_streamlit_chat_e2e.py` (extend), `tests/test_recommendation_live.py` (extend).

**Interfaces produced by this plan:**
- `versions.current_configuration_versions(settings: Settings) -> ConfigurationVersions`
- `versions.GOVERNED_RECOMMENDATION_VERSION: str` (moved from `orchestration/pipeline.py`, re-exported there for backward compatibility)
- `contracts.ResultSource(StrEnum)`: `LIVE = "live"`, `REPLAY = "replay"`
- `replay.contracts.ReplayArtifact(schema_version: str, scenario: ScenarioName, recorded_at: datetime, configuration_versions: ConfigurationVersions, chat_response: ChatResponse)`
- `replay.contracts.REPLAY_ARTIFACT_SCHEMA_VERSION: str`
- `replay.store.ReplayArtifactIncompatibleError(ValueError)`, `replay.store.ReplayArtifactMissingError(FileNotFoundError)`
- `replay.store.replay_artifact_path(scenario: ScenarioName, settings: Settings) -> Path`
- `replay.store.save_replay_artifact(response: ChatResponse, settings: Settings) -> ReplayArtifact`
- `replay.store.load_replay_artifact(scenario: ScenarioName, settings: Settings) -> ReplayArtifact`
- `replay.pipeline.run_replay_portfolio_workflow(question: PortfolioQuestion, settings: Settings | None = None) -> WorkflowResult`
- `workflow.run_portfolio_workflow(question, settings=None, synthesizer=None, *, use_baseline=False, event_listener=None, replay=False) -> WorkflowResult`
- `chat.contracts.ChatContext.force_replay: bool = False`
- `chat.contracts.ChatIntent.REPLAY`

---

### Task 1: Extract `versions.py` and add `source`/`output_schema_version` fields

**Files:**
- Create: `src/pricing_copilot/versions.py`
- Modify: `src/pricing_copilot/contracts.py`, `src/pricing_copilot/orchestration/pipeline.py`, `src/pricing_copilot/decisions/service.py`
- Test: `tests/test_versions.py`, existing `tests/test_decisions_contracts.py`/`tests/test_orchestration_pipeline.py` (must stay green unmodified)

**Interfaces:**
- Produces: `versions.current_configuration_versions`, `versions.GOVERNED_RECOMMENDATION_VERSION`, `contracts.ResultSource`.

This is mostly a refactor (pure extraction of duplicated logic) plus additive, defaulted fields - no existing behavior changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_versions.py
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.versions import GOVERNED_RECOMMENDATION_VERSION, current_configuration_versions


def test_current_configuration_versions_returns_a_fully_populated_object() -> None:
    versions = current_configuration_versions(get_settings())
    assert isinstance(versions, ConfigurationVersions)
    assert versions.recommendation_version == GOVERNED_RECOMMENDATION_VERSION
    assert versions.output_schema_version


def test_current_configuration_versions_is_deterministic_for_the_same_settings() -> None:
    settings = get_settings()
    assert current_configuration_versions(settings) == current_configuration_versions(settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_versions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.versions'`.

- [ ] **Step 3: Add `ResultSource` and `output_schema_version` to `contracts.py`**

Add near the other `StrEnum`s in `src/pricing_copilot/contracts.py`:

```python
class ResultSource(StrEnum):
    LIVE = "live"
    REPLAY = "replay"
```

Add `output_schema_version` to `ConfigurationVersions` (after `recommendation_policy_version`):

```python
    output_schema_version: str = "workflow-result-schema-v1"
```

Add `source: ResultSource = ResultSource.LIVE` to `WorkflowResult`, `DecisionRequest`, and `AnalystDecision` (each right after their existing fields - keep field order stable, append at the end of each model).

- [ ] **Step 4: Create `versions.py`**

```python
# src/pricing_copilot/versions.py
from __future__ import annotations

from pricing_copilot.config import Settings
from pricing_copilot.contracts import ConfigurationVersions
from pricing_copilot.data.generation import DEFAULT_SCENARIO_SEED, DEFAULT_SCENARIO_VERSION
from pricing_copilot.governance.registry import AGENT_REGISTRY_VERSION
from pricing_copilot.observability.trace import POLICY_VERSION, PROMPT_VERSION, TOOL_VERSION
from pricing_copilot.recommendation.governance import GOVERNANCE_VERSION

GOVERNED_RECOMMENDATION_VERSION = "governed-multi-agent-v1"


def current_configuration_versions(settings: Settings) -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name=settings.model_name,
        recommendation_version=GOVERNED_RECOMMENDATION_VERSION,
        governance_version=GOVERNANCE_VERSION,
        scenario_seed=DEFAULT_SCENARIO_SEED,
        scenario_version=DEFAULT_SCENARIO_VERSION,
        max_price_movement_pct=settings.policy.max_price_movement_pct,
        prompt_version=PROMPT_VERSION,
        agent_registry_version=AGENT_REGISTRY_VERSION,
        tool_version=TOOL_VERSION,
        dataset_version=DEFAULT_SCENARIO_VERSION,
        recommendation_policy_version=POLICY_VERSION,
    )
```

- [ ] **Step 5: Point `orchestration/pipeline.py` at `versions.py`**

Replace the local `GOVERNED_RECOMMENDATION_VERSION = "governed-multi-agent-v1"` constant and the `_configuration_versions` function in `orchestration/pipeline.py` with an import:

```python
from pricing_copilot.versions import GOVERNED_RECOMMENDATION_VERSION, current_configuration_versions
```

Replace every call site of `_configuration_versions(settings)` in that file with `current_configuration_versions(settings)`, and delete the now-unused local function. `GOVERNED_RECOMMENDATION_VERSION` stays importable from `orchestration.pipeline` too (the import above re-exports it), so `decisions/service.py`'s existing `from pricing_copilot.orchestration.pipeline import GOVERNED_RECOMMENDATION_VERSION` keeps working unmodified for now (Step 6 will move it anyway).

- [ ] **Step 6: Simplify `decisions/service.py`**

Replace the manually-constructed `ConfigurationVersions(...)` block in `record_analyst_decision` with:

```python
from pricing_copilot.versions import current_configuration_versions
...
    configuration_versions = current_configuration_versions(settings)
```

Remove the now-unused imports (`DEFAULT_SCENARIO_SEED`, `DEFAULT_SCENARIO_VERSION`, `AGENT_REGISTRY_VERSION`, `POLICY_VERSION`, `PROMPT_VERSION`, `TOOL_VERSION`, `GOVERNED_RECOMMENDATION_VERSION`, `GOVERNANCE_VERSION`) that are no longer referenced directly. Add `source=request.source` to the `AnalystDecision(...)` construction.

- [ ] **Step 7: Run tests to verify everything passes**

Run: `uv run pytest tests/test_versions.py tests/test_orchestration_pipeline.py tests/test_decisions_service.py tests/test_decisions_contracts.py -v`
Expected: All PASS, including every pre-existing case unmodified (new fields all have defaults).

- [ ] **Step 8: Commit**

```bash
git add src/pricing_copilot/versions.py src/pricing_copilot/contracts.py src/pricing_copilot/orchestration/pipeline.py src/pricing_copilot/decisions/service.py tests/test_versions.py
git commit -m "refactor: extract shared configuration-versions builder, add ResultSource"
```

---

### Task 2: Replay artifact contract and store

**Files:**
- Create: `src/pricing_copilot/replay/__init__.py`, `src/pricing_copilot/replay/contracts.py`, `src/pricing_copilot/replay/store.py`
- Modify: `src/pricing_copilot/config.py`
- Test: `tests/test_replay_store.py`

**Interfaces:**
- Consumes: `chat.contracts.ChatResponse`, `versions.current_configuration_versions`.
- Produces: `ReplayArtifact`, `REPLAY_ARTIFACT_SCHEMA_VERSION`, `save_replay_artifact`, `load_replay_artifact`, `replay_artifact_path`, `ReplayArtifactIncompatibleError`, `ReplayArtifactMissingError`.

- [ ] **Step 1: Add the settings field**

Add to `Settings` in `config.py`, next to `trace_directory`:

```python
    replay_directory: Path = Path("var/replay")
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_replay_store.py
from datetime import date
from pathlib import Path

import pytest

from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    ScenarioName,
    Segment,
    WorkflowResult,
)
from pricing_copilot.replay.store import (
    ReplayArtifactIncompatibleError,
    ReplayArtifactMissingError,
    load_replay_artifact,
    save_replay_artifact,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(replay_directory=tmp_path / "replay")


def _workflow_result() -> WorkflowResult:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    return WorkflowResult(
        question=question,
        specialist_reports=[],
        recommendation=Recommendation(
            action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
        ),
        governance_outcome=GovernanceOutcome(approved=True),
        missing_evidence=[],
    )


def _chat_response() -> ChatResponse:
    return ChatResponse(
        intent=ChatIntent.PRICING_ANALYSIS,
        context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
        message="The governed workflow recommends increase.",
        workflow_result=_workflow_result(),
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    saved = save_replay_artifact(_chat_response(), settings)
    assert saved.scenario is ScenarioName.CONTROLLED_INCREASE

    loaded = load_replay_artifact(ScenarioName.CONTROLLED_INCREASE, settings)
    assert loaded.chat_response.workflow_result is not None
    assert loaded.chat_response.workflow_result.recommendation.action is RecommendationAction.INCREASE


def test_load_missing_artifact_raises_missing_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ReplayArtifactMissingError):
        load_replay_artifact(ScenarioName.RETENTION_CONCERN, settings)


def test_load_rejects_an_artifact_with_a_stale_configuration_version(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_replay_artifact(_chat_response(), settings)
    path = settings.replay_directory / f"{ScenarioName.CONTROLLED_INCREASE.value}.json"
    stale = path.read_text().replace('"governance-version"', '"governance-version"').replace(
        "deterministic-governance-v1", "deterministic-governance-v0-stale"
    )
    path.write_text(stale)

    with pytest.raises(ReplayArtifactIncompatibleError, match="governance_version"):
        load_replay_artifact(ScenarioName.CONTROLLED_INCREASE, settings)
```

(Fix the deliberately-awkward `stale` string-replace above once you know the exact serialized field name - `ConfigurationVersions.governance_version` serializes as `"governance_version"`, not `"governance-version"`; write the replace against the real JSON key so the test actually corrupts the field it claims to.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_replay_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `replay/contracts.py`**

```python
# src/pricing_copilot/replay/contracts.py
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from pricing_copilot.chat.contracts import ChatResponse
from pricing_copilot.contracts import ConfigurationVersions, ScenarioName

REPLAY_ARTIFACT_SCHEMA_VERSION = "replay-artifact-schema-v1"


class ReplayArtifact(BaseModel):
    schema_version: str
    scenario: ScenarioName
    recorded_at: datetime
    configuration_versions: ConfigurationVersions
    chat_response: ChatResponse
```

- [ ] **Step 5: Implement `replay/store.py`**

```python
# src/pricing_copilot/replay/store.py
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pricing_copilot.chat.contracts import ChatResponse
from pricing_copilot.config import Settings
from pricing_copilot.contracts import ScenarioName
from pricing_copilot.replay.contracts import REPLAY_ARTIFACT_SCHEMA_VERSION, ReplayArtifact
from pricing_copilot.versions import current_configuration_versions


class ReplayArtifactIncompatibleError(ValueError):
    """Raised when a stored replay artifact's schema or configuration versions no longer
    match the running configuration - it must be re-recorded, not silently served."""


class ReplayArtifactMissingError(FileNotFoundError):
    """Raised when no replay artifact has been recorded for a scenario yet."""


def replay_artifact_path(scenario: ScenarioName, settings: Settings) -> Path:
    return Path(settings.replay_directory) / f"{scenario.value}.json"


def save_replay_artifact(response: ChatResponse, settings: Settings) -> ReplayArtifact:
    if response.workflow_result is None:
        raise ValueError("Cannot save a replay artifact for a response with no workflow_result.")
    artifact = ReplayArtifact(
        schema_version=REPLAY_ARTIFACT_SCHEMA_VERSION,
        scenario=response.context.scenario,
        recorded_at=datetime.now(UTC),
        configuration_versions=current_configuration_versions(settings),
        chat_response=response,
    )
    path = replay_artifact_path(artifact.scenario, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(indent=2))
    return artifact


def load_replay_artifact(scenario: ScenarioName, settings: Settings) -> ReplayArtifact:
    path = replay_artifact_path(scenario, settings)
    if not path.exists():
        raise ReplayArtifactMissingError(
            f"No replay artifact recorded for scenario {scenario.value!r} at {path}."
        )
    artifact = ReplayArtifact.model_validate_json(path.read_text())

    if artifact.schema_version != REPLAY_ARTIFACT_SCHEMA_VERSION:
        raise ReplayArtifactIncompatibleError(
            f"schema_version: artifact has {artifact.schema_version!r}, current code requires "
            f"{REPLAY_ARTIFACT_SCHEMA_VERSION!r}. Re-record this artifact."
        )
    current = current_configuration_versions(_settings_from_artifact_context(settings))
    if artifact.configuration_versions != current:
        mismatched = [
            field
            for field in ConfigurationVersions_fields()
            if getattr(artifact.configuration_versions, field) != getattr(current, field)
        ]
        raise ReplayArtifactIncompatibleError(
            f"{', '.join(mismatched)}: artifact configuration versions no longer match the "
            "running configuration. Re-record this artifact."
        )
    return artifact
```

(The `_settings_from_artifact_context`/`ConfigurationVersions_fields` names above are placeholders to fix in Step 6 - `current_configuration_versions` already takes `settings` directly, and you can get the field names from `ConfigurationVersions.model_fields`. Do not leave placeholder names in the final file.)

- [ ] **Step 6: Fix the placeholder and finish the mismatch-reporting logic**

Replace the tail of `load_replay_artifact` with:

```python
    current = current_configuration_versions(settings)
    if artifact.configuration_versions != current:
        mismatched = [
            field
            for field in type(current).model_fields
            if getattr(artifact.configuration_versions, field) != getattr(current, field)
        ]
        raise ReplayArtifactIncompatibleError(
            f"{', '.join(mismatched)}: artifact configuration versions no longer match the "
            "running configuration. Re-record this artifact."
        )
    return artifact
```

Remove the unused `ConfigurationVersions` import if it's no longer referenced directly (it's still needed for the type annotation context, keep it if MyPy needs it - check after Task 12's MyPy run).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_replay_store.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/pricing_copilot/config.py src/pricing_copilot/replay/ tests/test_replay_store.py
git commit -m "feat: add replay artifact contract, save/load, and version-compatibility validation"
```

---

### Task 3: Safe-fail the live pipeline's missing-credentials case

**Files:**
- Modify: `src/pricing_copilot/orchestration/pipeline.py`
- Test: `tests/test_orchestration_pipeline.py`

**Interfaces:** none new - hardens existing `run_governed_portfolio_workflow`.

Currently `get_default_orchestration(settings)` raises a bare `RuntimeError` when Azure credentials aren't configured, and that call happens *before* `asyncio.run(...)` in `run_governed_portfolio_workflow` - outside every safety net the pipeline already has for timeouts and generic exceptions. This is exactly the "unavailable model API" failure mode issue #9 requires a clear user-facing state for.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_orchestration_pipeline.py
from unittest.mock import patch

from pricing_copilot.contracts import RecommendationAction


def test_missing_credentials_produces_a_safe_investigate_result_not_a_crash() -> None:
    with patch(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        side_effect=RuntimeError("Azure OpenAI credentials are not configured."),
    ):
        result = run_governed_portfolio_workflow(_question(ScenarioName.CONTROLLED_INCREASE))

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.missing_evidence
    assert "workflow:" in result.missing_evidence[0].reason
    assert "unavailable" in result.missing_evidence[0].reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestration_pipeline.py::test_missing_credentials_produces_a_safe_investigate_result_not_a_crash -v`
Expected: FAIL - the patched `RuntimeError` propagates uncaught out of `run_governed_portfolio_workflow`.

- [ ] **Step 3: Wrap the credential-check call site**

In `run_governed_portfolio_workflow`, replace the `active = get_default_orchestration(...)` branches with a try/except that converts the failure into the standard safe-failure result:

```python
    if orchestration is not None:
        active = orchestration
    else:
        try:
            active = get_default_orchestration(settings, event_listener=event_listener)
        except RuntimeError as exc:
            return data_quality_investigation_result(
                question, f"workflow: model API is unavailable ({exc})."
            )
```

(This replaces the previous `elif event_listener is None: ... else: ...` two-branch form - `get_default_orchestration` already accepts `event_listener=None` as a no-op default, so one branch covers both cases.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_orchestration_pipeline.py -v`
Expected: All PASS, including every pre-existing case.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/orchestration/pipeline.py tests/test_orchestration_pipeline.py
git commit -m "fix: safely fail instead of crashing when the model API is unavailable"
```

---

### Task 4: `run_replay_portfolio_workflow` and the `replay=True` dispatch

**Files:**
- Create: `src/pricing_copilot/replay/pipeline.py`
- Modify: `src/pricing_copilot/workflow.py`
- Test: `tests/test_replay_pipeline.py`, `tests/test_workflow.py` (extend)

**Interfaces:**
- Consumes: `replay.store.load_replay_artifact`, `workflow_common.IMPLEMENTED_DATA_SCENARIOS`, `workflow_common.missing_evidence_workflow_result`.
- Produces: `run_replay_portfolio_workflow`, `run_portfolio_workflow(..., replay=False)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replay_pipeline.py
from datetime import date
from pathlib import Path

import pytest

from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    ResultSource,
    ScenarioName,
    Segment,
    WorkflowResult,
)
from pricing_copilot.replay.pipeline import run_replay_portfolio_workflow
from pricing_copilot.replay.store import ReplayArtifactMissingError, save_replay_artifact


def _question(scenario: ScenarioName | None) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=scenario,
    )


def _record(settings: Settings) -> None:
    question = _question(ScenarioName.CONTROLLED_INCREASE)
    result = WorkflowResult(
        question=question,
        specialist_reports=[],
        recommendation=Recommendation(
            action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
        ),
        governance_outcome=GovernanceOutcome(approved=True),
        missing_evidence=[],
    )
    response = ChatResponse(
        intent=ChatIntent.PRICING_ANALYSIS,
        context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
        message="increase",
        workflow_result=result,
    )
    save_replay_artifact(response, settings)


def test_run_replay_portfolio_workflow_returns_a_source_stamped_result(tmp_path: Path) -> None:
    settings = Settings(replay_directory=tmp_path / "replay")
    _record(settings)

    result = run_replay_portfolio_workflow(_question(ScenarioName.CONTROLLED_INCREASE), settings)

    assert result.source is ResultSource.REPLAY
    assert result.recommendation.action is RecommendationAction.INCREASE


def test_run_replay_portfolio_workflow_raises_when_nothing_is_recorded(tmp_path: Path) -> None:
    settings = Settings(replay_directory=tmp_path / "replay")
    with pytest.raises(ReplayArtifactMissingError):
        run_replay_portfolio_workflow(_question(ScenarioName.RETENTION_CONCERN), settings)


def test_run_replay_portfolio_workflow_returns_missing_evidence_for_no_scenario(
    tmp_path: Path,
) -> None:
    settings = Settings(replay_directory=tmp_path / "replay")
    result = run_replay_portfolio_workflow(_question(None), settings)
    assert result.missing_evidence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_replay_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `replay/pipeline.py`**

```python
# src/pricing_copilot/replay/pipeline.py
from __future__ import annotations

from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import PortfolioQuestion, ResultSource, WorkflowResult
from pricing_copilot.replay.store import load_replay_artifact
from pricing_copilot.workflow_common import IMPLEMENTED_DATA_SCENARIOS, missing_evidence_workflow_result


def run_replay_portfolio_workflow(
    question: PortfolioQuestion, settings: Settings | None = None
) -> WorkflowResult:
    settings = settings or get_settings()
    if question.scenario not in IMPLEMENTED_DATA_SCENARIOS:
        return missing_evidence_workflow_result(question)
    artifact = load_replay_artifact(question.scenario, settings)
    result = artifact.chat_response.workflow_result
    if result is None:  # pragma: no cover - save_replay_artifact never persists a null result
        raise ValueError(f"Replay artifact for {question.scenario.value} has no workflow_result.")
    return result.model_copy(update={"source": ResultSource.REPLAY})
```

- [ ] **Step 4: Run replay-pipeline tests to verify they pass**

Run: `uv run pytest tests/test_replay_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Wire `replay=True` into `workflow.run_portfolio_workflow`**

```python
# add to tests/test_workflow.py
def test_replay_flag_routes_to_the_replay_pipeline(tmp_path) -> None:
    from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
    from pricing_copilot.config import Settings
    from pricing_copilot.contracts import GovernanceOutcome, Recommendation, ResultSource
    from pricing_copilot.replay.store import save_replay_artifact

    settings = Settings(replay_directory=tmp_path / "replay")
    question = _question().model_copy(update={"scenario": ScenarioName.CONTROLLED_INCREASE})
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="increase",
            workflow_result=WorkflowResult(
                question=question,
                specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True),
                missing_evidence=[],
            ),
        ),
        settings,
    )

    result = run_portfolio_workflow(question, settings, replay=True)

    assert result.source is ResultSource.REPLAY
    assert result.recommendation.action is RecommendationAction.INCREASE
```

Run it to see it fail (`TypeError: run_portfolio_workflow() got an unexpected keyword argument 'replay'`), then add the parameter in `workflow.py`:

```python
def run_portfolio_workflow(
    question: PortfolioQuestion,
    settings: Settings | None = None,
    synthesizer: RecommendationSynthesizer | None = None,
    *,
    use_baseline: bool = False,
    event_listener: TraceEventListener | None = None,
    replay: bool = False,
) -> WorkflowResult:
    """..."""
    if replay:
        from pricing_copilot.replay.pipeline import run_replay_portfolio_workflow

        validate_portfolio_combination(question.product, question.region, question.segment)
        return run_replay_portfolio_workflow(question, settings)
    if use_baseline or synthesizer is not None:
        return run_baseline_portfolio_workflow(question, settings, synthesizer)

    validate_portfolio_combination(question.product, question.region, question.segment)
    return run_governed_portfolio_workflow(question, settings, event_listener=event_listener)
```

(The import is deferred inside the function body to avoid a circular import - `replay.pipeline` imports from `workflow_common`, not `workflow`, so this is actually safe as a top-level import too; use whichever reads cleaner after checking there's no cycle. Prefer a top-level import if `uv run mypy` and `uv run pytest` both stay clean with one.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow.py tests/test_replay_pipeline.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add src/pricing_copilot/replay/pipeline.py src/pricing_copilot/workflow.py tests/test_replay_pipeline.py tests/test_workflow.py
git commit -m "feat: add run_replay_portfolio_workflow and wire replay=True through run_portfolio_workflow"
```

---

### Task 5: Chat replay intent, explicit live-failure handling, `force_replay`

**Files:**
- Modify: `src/pricing_copilot/chat/contracts.py`, `src/pricing_copilot/chat/service.py`
- Test: `tests/test_chat_service.py`

**Interfaces:**
- Consumes: `run_replay_portfolio_workflow` (via `run_portfolio_workflow(..., replay=True)`).
- Produces: `ChatIntent.REPLAY`, `ChatContext.force_replay`, `ChatResponse.source`.

- [ ] **Step 1: Add the new contract fields**

In `chat/contracts.py`:

```python
class ChatIntent(StrEnum):
    DATA_RETRIEVAL = "data_retrieval"
    MULTI_SOURCE_SUMMARY = "multi_source_summary"
    PRICING_ANALYSIS = "pricing_analysis"
    REPLAY = "replay"
    EVALUATION = "evaluation"
    DRIFT = "drift"
    HELP = "help"
    UNSUPPORTED = "unsupported"
```

```python
class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioName = ScenarioName.CONTROLLED_INCREASE
    force_replay: bool = False
```

```python
class ChatResponse(BaseModel):
    ...
    source: ResultSource = ResultSource.LIVE
```

(Import `ResultSource` from `pricing_copilot.contracts` alongside the existing `ScenarioName, WorkflowResult` import.)

- [ ] **Step 2: Write the failing tests**

```python
# add to tests/test_chat_service.py
from pricing_copilot.contracts import ResultSource


def test_replay_keyword_serves_a_labeled_cached_result(
    service: ChatService, tmp_path: Path
) -> None:
    from datetime import date

    from pricing_copilot.chat.contracts import ChatContext
    from pricing_copilot.contracts import (
        AnalysisPeriod, GovernanceOutcome, PortfolioQuestion, Product, Recommendation,
        RecommendationAction, Region, Segment, WorkflowResult,
    )
    from pricing_copilot.replay.store import save_replay_artifact

    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR, region=Region.NORTH_WEST, segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question, specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True), missing_evidence=[],
            ),
        ),
        service.settings,
    )

    response = service.submit(
        "Replay the controlled increase scenario",
        ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
    )

    assert response.intent is ChatIntent.REPLAY
    assert response.source is ResultSource.REPLAY
    assert "replay" in response.message.lower()
    assert response.workflow_result is not None
    assert response.workflow_result.source is ResultSource.REPLAY


def test_replay_without_a_recorded_artifact_fails_gracefully(service: ChatService) -> None:
    response = service.submit(
        "Replay the retention concern scenario",
        ChatContext(scenario=ScenarioName.RETENTION_CONCERN),
    )
    assert response.intent is ChatIntent.REPLAY
    assert not response.refused
    assert "not" in response.message.lower()


def test_force_replay_context_flag_bypasses_keyword_matching(
    service: ChatService,
) -> None:
    from pricing_copilot.replay.store import save_replay_artifact

    from datetime import date
    from pricing_copilot.contracts import (
        AnalysisPeriod, GovernanceOutcome, PortfolioQuestion, Product, Recommendation,
        RecommendationAction, Region, Segment, WorkflowResult,
    )

    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR, region=Region.NORTH_WEST, segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question, specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True), missing_evidence=[],
            ),
        ),
        service.settings,
    )

    response = service.submit(
        "Recommend a pricing action",
        ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE, force_replay=True),
    )

    assert response.source is ResultSource.REPLAY
```

(Consolidate the duplicated fixture-building code across these three tests into one module-level helper, e.g. `_save_controlled_increase_replay(service)`, before finishing this task - don't leave three copies of the same setup.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: The three new tests FAIL (`ChatIntent.REPLAY` doesn't exist yet / behavior not implemented).

- [ ] **Step 4: Remove "replay" from the evaluation keyword list and add replay routing**

In `chat/service.py`, change `_intent_for`:

```python
    @staticmethod
    def _intent_for(message: str) -> ChatIntent:
        lowered = message.lower()
        if any(word in lowered for word in ("evaluate", "evaluation", "golden case")):
            return ChatIntent.EVALUATION
        if any(phrase in lowered for phrase in ("replay", "cached run", "use the cache")):
            return ChatIntent.REPLAY
        if any(word in lowered for word in ("drift", "monitoring", "monitor model")):
            return ChatIntent.DRIFT
        ...
```

In `submit`, check `force_replay` before intent classification, and route `ChatIntent.REPLAY`:

```python
        active_context = ChatContext(
            scenario=self._scenario_for(normalized, active_context.scenario),
            force_replay=active_context.force_replay,
        )
        intent = ChatIntent.REPLAY if active_context.force_replay else self._intent_for(normalized)
        ...
        if intent is ChatIntent.REPLAY:
            return self._run_replay(active_context, on_activity)
```

Add the handler:

```python
    def _run_replay(
        self, context: ChatContext, listener: ActivityListener | None
    ) -> ChatResponse:
        from pricing_copilot.replay.store import ReplayArtifactIncompatibleError, ReplayArtifactMissingError, load_replay_artifact

        activities: list[ChatActivity] = []
        try:
            artifact = load_replay_artifact(context.scenario, self.settings)
        except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.UNAVAILABLE,
                    label="Replay is not available for this scenario",
                    purpose="Reporting that no valid replay artifact is recorded.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.REPLAY,
                context=context,
                message=(
                    f"A replay is not available for the {context.scenario.value} scenario yet "
                    f"({exc}). Ask for a live recommendation instead, or record a replay "
                    "artifact first."
                ),
                activities=activities,
            )
        self._emit(
            ChatActivity(
                status=ActivityStatus.COMPLETED,
                label="Replaying a previously validated cached run",
                purpose="Serving a version-checked replay artifact instead of a live model call.",
            ),
            activities,
            listener,
        )
        response = artifact.chat_response
        replayed = response.model_copy(
            update={
                "message": f"**[REPLAY - not a live analysis]** {response.message}",
                "activities": activities,
                "source": ResultSource.REPLAY,
                "workflow_result": (
                    response.workflow_result.model_copy(update={"source": ResultSource.REPLAY})
                    if response.workflow_result is not None
                    else None
                ),
                "context": context,
            }
        )
        return replayed
```

Add `from pricing_copilot.contracts import ResultSource` to the imports at the top of `chat/service.py`.

- [ ] **Step 5: Detect a live workflow-level failure and offer replay explicitly (not automatically)**

In `_run_pricing_analysis`, after `result = run_portfolio_workflow(...)`, check for the `"workflow:"` failure-reason prefix (the convention Task 3 and the pre-existing timeout/generic-exception paths use) and respond honestly instead of presenting it as a normal investigate outcome:

```python
        result = run_portfolio_workflow(question, self.settings, event_listener=record_trace_event)
        live_failure_reason = next(
            (item.reason for item in result.missing_evidence if item.reason.startswith("workflow:")),
            None,
        )
        if live_failure_reason is not None:
            self._emit(
                ChatActivity(
                    status=ActivityStatus.FAILED,
                    label="Live analysis is currently unavailable",
                    purpose="Reporting a live failure without silently switching to replay.",
                ),
                activities,
                listener,
            )
            return ChatResponse(
                intent=ChatIntent.PRICING_ANALYSIS,
                context=context,
                message=(
                    f"Live analysis could not complete right now ({live_failure_reason}). Ask "
                    f"me to 'replay the {context.scenario.value} scenario' to see a previously "
                    "validated, clearly labeled cached run instead."
                ),
                activities=activities,
            )
        recommendation = result.recommendation
        ...
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: All PASS, including every pre-existing case (the evaluation-intent test for "replay" no longer exists as a case - confirm no pre-existing test asserted "replay" maps to EVALUATION; if one does, that test's premise is now intentionally wrong and must be updated to use "evaluate" or "golden case" instead).

- [ ] **Step 7: Commit**

```bash
git add src/pricing_copilot/chat/contracts.py src/pricing_copilot/chat/service.py tests/test_chat_service.py
git commit -m "feat: add explicit chat replay intent and honest live-failure reporting"
```

---

### Task 6: Streamlit replay labeling and the "try replay instead" button

**Files:**
- Modify: `src/pricing_copilot/streamlit_app.py`
- Test: `tests/test_streamlit_chat_e2e.py`

**Interfaces:** none new - consumes `ChatResponse.source`, `ChatContext.force_replay`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_streamlit_chat_e2e.py
def test_replay_keyword_shows_a_prominent_replay_label(tmp_path, monkeypatch) -> None:
    import json
    from datetime import date

    from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
    from pricing_copilot.contracts import (
        AnalysisPeriod, GovernanceOutcome, PortfolioQuestion, Product, Recommendation,
        RecommendationAction, Region, ScenarioName, Segment, WorkflowResult,
    )
    from pricing_copilot.replay.store import save_replay_artifact
    from pricing_copilot.config import Settings

    replay_dir = tmp_path / "replay"
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(replay_dir))
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR, region=Region.NORTH_WEST, segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question, specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True), missing_evidence=[],
            ),
        ),
        Settings(replay_directory=replay_dir),
    )

    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()
    app.chat_input[0].set_value("Replay the controlled increase scenario")
    app.run()

    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown) + "\n".join(
        w.body for w in app.warning
    )
    assert "REPLAY" in markdown
```

(Confirm the exact `AppTest` API for reading rendered `st.warning`/`st.error` bodies - check `streamlit.testing.v1.AppTest`'s attributes, e.g. `app.warning`, before finalizing this assertion; adjust to whatever the installed Streamlit version's test API actually exposes.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`
Expected: FAIL - no replay label is currently rendered.

- [ ] **Step 3: Add the replay banner to `_render_response`**

In `streamlit_app.py`, at the top of `_render_response` (before rendering the message):

```python
def _render_response(response: ChatResponse, message_number: int, *, can_record: bool) -> None:
    if response.source is ResultSource.REPLAY:
        st.warning(
            "REPLAY MODE - this is a cached, previously validated run, not a live analysis.",
            icon="🔁",
        )
    st.markdown(response.message)
    ...
```

Add `from pricing_copilot.contracts import ResultSource` (alongside the existing `WorkflowResult` import from `pricing_copilot.contracts`).

- [ ] **Step 4: Add the "try replay instead" button after a detected live failure**

In the chat-input handling block, after `response = ChatService().submit(prompt, on_activity=show_activity)`, detect the live-failure phrasing and offer a button that resubmits the *same* prompt with `force_replay=True`:

```python
        if "Live analysis could not complete" in response.message:
            if st.button("Try replay instead", key=f"replay_retry_{message_number}"):
                retry_context = ChatContext(scenario=response.context.scenario, force_replay=True)
                response = ChatService().submit(prompt, retry_context, on_activity=show_activity)
```

(Place this before the final `_render_response` call for this turn so the button's result, if clicked, is what actually gets rendered and appended to `chat_messages`. Streamlit's rerun-on-interaction model means the button click triggers a full script rerun - the surrounding chat-input block already only runs once per new prompt, so wire this so the *replayed* response replaces `response` before the trailing `_render_response`/`st.session_state.chat_messages.append` calls, not as a separate render path.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_streamlit_chat_e2e.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_chat_e2e.py
git commit -m "feat: add prominent replay labeling and a try-replay-instead button"
```

---

### Task 7: CLI - `--replay`, `--json`, `--record-replay-artifacts`, readable summary

**Files:**
- Modify: `src/pricing_copilot/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_cli.py
import json


def test_cli_default_output_is_a_readable_summary_not_raw_json(capsys) -> None:
    from pricing_copilot.cli import main

    exit_code = main([
        "--product", "personal_motor", "--region", "north_west", "--segment", "renewal",
        "--start-month", "2026-01-01", "--end-month", "2026-06-01",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Recommendation:" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_cli_json_flag_emits_stable_json(capsys) -> None:
    from pricing_copilot.cli import main

    exit_code = main([
        "--product", "personal_motor", "--region", "north_west", "--segment", "renewal",
        "--start-month", "2026-01-01", "--end-month", "2026-06-01", "--json",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["recommendation"]["action"] == "investigate"


def test_cli_replay_flag_serves_a_recorded_artifact(tmp_path, monkeypatch, capsys) -> None:
    from datetime import date

    from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
    from pricing_copilot.cli import main
    from pricing_copilot.config import Settings
    from pricing_copilot.contracts import (
        AnalysisPeriod, GovernanceOutcome, PortfolioQuestion, Product, Recommendation,
        RecommendationAction, Region, ScenarioName, Segment, WorkflowResult,
    )
    from pricing_copilot.replay.store import save_replay_artifact

    replay_dir = tmp_path / "replay"
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(replay_dir))
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR, region=Region.NORTH_WEST, segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question, specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True), missing_evidence=[],
            ),
        ),
        Settings(replay_directory=replay_dir),
    )

    exit_code = main([
        "--product", "personal_motor", "--region", "north_west", "--segment", "renewal",
        "--start-month", "2025-07-01", "--end-month", "2025-12-01",
        "--scenario", "controlled_increase", "--replay", "--json",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["source"] == "replay"
    assert payload["recommendation"]["action"] == "increase"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: The three new tests FAIL (`--json`/`--replay` flags don't exist; output format hasn't changed).

- [ ] **Step 3: Add the flags and readable-summary rendering**

In `build_parser`, add:

```python
    parser.add_argument("--replay", action="store_true", help="Serve a recorded replay artifact instead of a live analysis.")
    parser.add_argument("--json", action="store_true", help="Emit the full result as stable JSON instead of a readable summary.")
    parser.add_argument(
        "--record-replay-artifacts",
        action="store_true",
        help="Run all three supported scenarios live and save their replay artifacts.",
    )
```

Add a summary-rendering helper and the `--record-replay-artifacts` branch, and thread `--replay` through the `run_portfolio_workflow` call:

```python
def _print_summary(result) -> None:  # noqa: ANN001 - WorkflowResult, kept untyped to avoid an extra import cycle here if any
    recommendation = result.recommendation
    print(f"Source: {result.source.value}")
    print(f"Recommendation: {recommendation.action.value}")
    if recommendation.price_range is not None:
        print(f"  Range: {recommendation.price_range.lower_pct:g}% to {recommendation.price_range.upper_pct:g}%")
    print(f"Rationale: {recommendation.rationale}")
    if result.missing_evidence:
        print("Missing evidence:")
        for item in result.missing_evidence:
            print(f"  - {item.domain.value}: {item.reason}")
    print("Specialist reports:")
    for report in result.specialist_reports:
        print(f"  - {report.domain.value} ({report.status}): {report.summary}")
```

In `main`, after building `question` (and before the existing `try: result = run_portfolio_workflow(...)` block), handle `--record-replay-artifacts` as an early return similar to `--build-data`:

```python
    if args.record_replay_artifacts:
        from pricing_copilot.chat.contracts import ChatContext
        from pricing_copilot.chat.service import ChatService
        from pricing_copilot.replay.store import save_replay_artifact

        service = ChatService()
        for scenario in ScenarioName:
            response = service.submit(
                "Recommend a pricing action", ChatContext(scenario=scenario)
            )
            if response.workflow_result is None:
                print(f"Skipped {scenario.value}: no workflow_result in response.", file=sys.stderr)
                continue
            save_replay_artifact(response, get_settings())
            print(f"Recorded replay artifact for {scenario.value}.")
        return 0
```

Update the live/replay call and output:

```python
    try:
        result = run_portfolio_workflow(question, replay=args.replay)
    except UnsupportedPortfolioError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
        print(f"Replay unavailable: {exc}", file=sys.stderr)
        return 1

    if args.save_trace:
        save_baseline_trace(result, Path(args.save_trace))

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_summary(result)
    return 0
```

Add the needed imports (`from pricing_copilot.replay.store import ReplayArtifactIncompatibleError, ReplayArtifactMissingError`, `ScenarioName` is already imported).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All PASS, including every pre-existing case (check whether any existing CLI test asserted on raw-JSON default output - if so, add `--json` to that test's argv rather than changing its expectation, since the default output format is intentionally changing in this task).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/cli.py tests/test_cli.py
git commit -m "feat: add CLI --replay, --json, and --record-replay-artifacts flags"
```

---

### Task 8: API - `replay` query parameter

**Files:**
- Modify: `src/pricing_copilot/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_api.py
def test_workflow_endpoint_replay_query_param_serves_a_recorded_artifact(
    tmp_path, monkeypatch
) -> None:
    from datetime import date

    from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
    from pricing_copilot.config import Settings
    from pricing_copilot.contracts import (
        AnalysisPeriod, GovernanceOutcome, PortfolioQuestion, Product, Recommendation,
        RecommendationAction, Region, ScenarioName, Segment, WorkflowResult,
    )
    from pricing_copilot.replay.store import save_replay_artifact

    replay_dir = tmp_path / "replay"
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(replay_dir))
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR, region=Region.NORTH_WEST, segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question, specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True), missing_evidence=[],
            ),
        ),
        Settings(replay_directory=replay_dir),
    )

    payload = question.model_dump(mode="json")
    response = client.post("/workflow?replay=true", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "replay"
    assert body["recommendation"]["action"] == "increase"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_workflow_endpoint_replay_query_param_serves_a_recorded_artifact -v`
Expected: FAIL - `replay` query param doesn't exist yet (422 or the field is silently ignored and a live/investigate result comes back).

- [ ] **Step 3: Add the query parameter**

```python
@app.post("/workflow", response_model=WorkflowResult)
def submit_portfolio_question(question: PortfolioQuestion, replay: bool = False) -> WorkflowResult:
    try:
        return run_portfolio_workflow(question, replay=replay)
    except UnsupportedPortfolioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Add the import: `from pricing_copilot.replay.store import ReplayArtifactIncompatibleError, ReplayArtifactMissingError`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/api.py tests/test_api.py
git commit -m "feat: add replay query parameter to the workflow endpoint"
```

---

### Task 9: Decision-record `source`, no-duplication proof

**Files:**
- Modify: none beyond Task 1's `decisions/service.py` change (already propagates `source=request.source`)
- Test: `tests/test_decisions_service.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_decisions_service.py
from pricing_copilot.contracts import ResultSource


def test_recorded_decision_preserves_the_replay_source() -> None:
    request = _decision_request(source=ResultSource.REPLAY)  # adapt to this file's existing request-building helper
    decision = record_analyst_decision(request, _settings(), _store())
    assert decision.source is ResultSource.REPLAY


def test_replaying_an_analysis_never_creates_a_decision_record_by_itself() -> None:
    store = _store()
    # calling run_replay_portfolio_workflow (or run_portfolio_workflow(..., replay=True)) must
    # never touch the decision store - assert the store stays empty after a replay call, then
    # confirm a real decision only appears once record_analyst_decision is explicitly invoked.
    ...
```

(Adapt both tests to this file's actual existing fixtures/helpers - read `tests/test_decisions_service.py` in full before writing these, since its exact helper names for building a `DecisionRequest`/`DecisionStore` aren't listed here and guessing them would produce a plan that doesn't match the real file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decisions_service.py -v`
Expected: FAIL on the `source` assertion (Task 1 already added the field and propagation, so this step mostly documents/locks the behavior - if it already passes because Task 1 was done correctly, that's fine, note it and move directly to Step 3's commit).

- [ ] **Step 3: Fix anything Task 1 missed, then run tests to verify they pass**

Run: `uv run pytest tests/test_decisions_service.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_decisions_service.py
git commit -m "test: prove decision records preserve source and replay never writes a decision"
```

---

### Task 10: Record and commit the three real replay artifacts

**Files:** none (generates `var/replay/*.json`)
- Modify: `.gitignore` if `var/` is currently fully ignored.

- [ ] **Step 1: Check whether `var/` is gitignored**

Run: `grep -n "^var" .gitignore`

- [ ] **Step 2: Carve out `var/replay/*.json` if needed**

If `.gitignore` has a blanket `var/` entry, add beneath it:

```
!var/replay/
!var/replay/*.json
```

- [ ] **Step 3: Generate the three artifacts against the real Azure endpoint**

Run: `uv run pricing-copilot --record-replay-artifacts`

Expected: three lines printed, one per scenario, and `var/replay/controlled_increase.json`, `var/replay/retention_concern.json`, `var/replay/conflicting_evidence.json` all exist.

- [ ] **Step 4: Inspect each artifact for correctness and safety**

Read all three files. Confirm: `schema_version` matches `REPLAY_ARTIFACT_SCHEMA_VERSION`, `configuration_versions` is fully populated, `chat_response.workflow_result.recommendation.action` matches the expected outcome per scenario (`increase` for controlled_increase, `hold`/`decrease` for retention_concern, `investigate` for conflicting_evidence - per the spec's testing decisions), and no Azure API key, endpoint, or other secret appears anywhere in the file (it shouldn't - nothing in `ChatResponse`/`WorkflowResult` carries credentials - but verify directly since these are the first files from this ticket committed to the repo).

- [ ] **Step 5: Prove artifact rejection works against a real stale copy**

Run: `uv run python3 -c "from pricing_copilot.replay.store import load_replay_artifact; from pricing_copilot.contracts import ScenarioName; from pricing_copilot.config import get_settings; print(load_replay_artifact(ScenarioName.CONTROLLED_INCREASE, get_settings()).scenario)"`
Expected: prints `controlled_increase` without raising - the freshly-recorded artifact matches the current running configuration.

- [ ] **Step 6: Commit**

```bash
git add .gitignore var/replay/controlled_increase.json var/replay/retention_concern.json var/replay/conflicting_evidence.json
git commit -m "feat: record and commit the three validated replay artifacts"
```

---

### Task 11: End-to-end coverage for every required failure/success path

**Files:**
- Modify: `tests/test_recommendation_live.py`
- Test: everything below is itself the test work for this task.

The acceptance criteria require end-to-end coverage of: live success, replay success, unavailable model, timeout, invalid structured output, and interface failure - for both the plain workflow (API/CLI) and the chat-first path. Live success and replay success are already covered by Tasks 4-8's tests plus the pre-existing `test_recommendation_live.py`. This task fills the remaining gaps with tests that don't already exist.

- [ ] **Step 1: Timeout produces a clear user-facing state (offline, no credentials needed)**

Add to `tests/test_orchestration_pipeline.py`:

```python
def test_workflow_timeout_produces_a_safe_investigate_result() -> None:
    settings = get_settings().model_copy(update={"max_workflow_seconds": 0.0001})

    async def _slow_synthesize(**_kwargs):
        await asyncio.sleep(1)

    recommendation = FakeRecommendationAgentRunner()
    recommendation.synthesize = _slow_synthesize  # type: ignore[method-assign]

    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        settings,
        orchestration=_bundle(recommendation=recommendation),
    )
    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert any("timeout" in item.reason.lower() or "time" in item.reason.lower() for item in result.missing_evidence)
```

(Confirm `Settings` supports `.model_copy(update=...)` - it's a pydantic-settings `BaseSettings`, which supports the same `model_copy` as any pydantic model; verify with a quick REPL check if unsure before relying on it in the test.)

- [ ] **Step 2: Invalid structured output produces a clear user-facing state (offline)**

Add to `tests/test_orchestration_pipeline.py`:

```python
def test_recommendation_agent_raising_a_model_behavior_error_fails_safely() -> None:
    from agents.exceptions import ModelBehaviorError

    class _BrokenRecommendationAgent(FakeRecommendationAgentRunner):
        async def synthesize(self, **_kwargs):
            raise ModelBehaviorError("invalid structured output")

    result = run_governed_portfolio_workflow(
        _question(ScenarioName.CONTROLLED_INCREASE),
        orchestration=_bundle(recommendation=_BrokenRecommendationAgent()),
    )
    assert result.recommendation.action is RecommendationAction.INVESTIGATE
```

- [ ] **Step 3: Chat surfaces a live failure with an explicit replay offer, not a crash (offline)**

Add to `tests/test_chat_service.py`:

```python
def test_chat_reports_a_live_failure_and_offers_an_explicit_replay_choice(
    service: ChatService,
) -> None:
    with patch(
        "pricing_copilot.orchestration.pipeline.get_default_orchestration",
        side_effect=RuntimeError("Azure OpenAI credentials are not configured."),
    ):
        response = service.submit("Recommend a pricing action")

    assert not response.refused
    assert "replay" in response.message.lower()
    assert response.workflow_result is None
```

- [ ] **Step 4: Interface failure - a broken Streamlit render doesn't take down the whole page silently**

Check whether `test_streamlit_chat_e2e.py` already has coverage for an exception path (search for `app.exception` assertions). If chat-level errors are already proven safe by the existing `assert not app.exception` pattern across all chat tests, note that this criterion is covered by the existing suite plus Task 6's new test and skip adding a redundant case. If not, add one exercising a malformed/missing replay artifact through the full Streamlit chat flow (an `AppTest` run of "replay the retention_concern scenario" with nothing recorded) and assert `not app.exception` and that a graceful message renders.

- [ ] **Step 5: Live CLI replay-vs-live smoke test against the real Azure endpoint**

Add to `tests/test_recommendation_live.py`:

```python
@requires_azure_openai
def test_live_replay_matches_the_recorded_artifact_for_controlled_increase() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR, region=Region.NORTH_WEST, segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    result = run_portfolio_workflow(question, replay=True)
    assert result.source is ResultSource.REPLAY
    assert result.recommendation.action is RecommendationAction.INCREASE
```

(This only passes once Task 10 has actually recorded the committed artifact with a matching question shape - run it after Task 10, not before.)

- [ ] **Step 6: Run the full new/changed test set**

Run: `uv run pytest tests/test_orchestration_pipeline.py tests/test_chat_service.py tests/test_streamlit_chat_e2e.py tests/test_recommendation_live.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_orchestration_pipeline.py tests/test_chat_service.py tests/test_streamlit_chat_e2e.py tests/test_recommendation_live.py
git commit -m "test: add end-to-end coverage for timeout, invalid output, and live-failure-to-replay paths"
```

---

### Task 12: Full quality suite and manual smoke test

**Files:** none (verification-only task)

- [ ] **Step 1: Run the full quality suite**

Run: `./scripts/quality.sh`
Expected: Ruff, MyPy strict, pytest (all suites including live), and Bandit all pass clean. Fix any findings before proceeding.

- [ ] **Step 2: Manually smoke-test the CLI**

```bash
uv run pricing-copilot --product personal_motor --region north_west --segment renewal --start-month 2025-07-01 --end-month 2025-12-01 --scenario controlled_increase
uv run pricing-copilot --product personal_motor --region north_west --segment renewal --start-month 2025-07-01 --end-month 2025-12-01 --scenario controlled_increase --replay
uv run pricing-copilot --product personal_motor --region north_west --segment renewal --start-month 2025-07-01 --end-month 2025-12-01 --scenario controlled_increase --json
```

Confirm: the first two produce readable, clearly-labeled-by-source summaries with different `Source:` lines; the third is valid JSON with `"source": "live"`.

- [ ] **Step 3: Manually smoke-test the chat interface (Streamlit, via the browser)**

Start Streamlit, ask "Recommend a pricing action" (live), then ask "Replay the controlled increase scenario" (replay) and confirm the prominent replay warning renders and the earlier live answer did not show it. If real credentials are briefly unset (temporarily rename `.env` or unset the env vars in a throwaway shell - do not delete or commit any credential changes), confirm asking for a recommendation produces the honest live-failure message with the replay suggestion, and that clicking "Try replay instead" renders the labeled cached result without crashing the page.

- [ ] **Step 4: Confirm decision recording still works end-to-end with a replayed result**

Run a replay via chat or CLI, then submit an analyst decision against that replayed recommendation through the API, and confirm the stored `AnalystDecision.source` is `"replay"`.

---

### Task 13: Commit, push, and close GitHub issue #9

- [ ] **Step 1:** Confirm `git status` is clean (all prior task commits already made).
- [ ] **Step 2:** `git push origin main` (the repository is now on `main`, not a feature branch - confirm with `git branch -vv` before pushing, since a parallel session already moved development there).
- [ ] **Step 3:** `gh issue close 9 --comment "..."` summarizing what was built, how each acceptance criterion (including the chat-first resilience requirements) is satisfied, the measured behavior of the three committed replay artifacts, and confirmation the full quality suite passes.

---

## Self-Review Notes

- **Spec coverage:** every bullet in issue #9's "Acceptance criteria" and "Chat-first resilience requirements" lists maps to a task - artifact existence/versioning (Tasks 2, 10), rejection of incompatible artifacts (Task 2), same typed contract live and replayed (Task 4 returns a real `WorkflowResult`/`ChatResponse`, never a parallel shape), prominent labeling (Task 6), explicit (not silent) replay choice (Tasks 3, 5, 6 - the button and keyword are both opt-in), timeout/invalid-output/unavailable-model clear states (Tasks 3, 11), one bounded retry (already existing `AgentRuntime` behavior, unchanged), API/CLI independent of Streamlit (Tasks 7, 8), CLI readable-summary-by-default plus stable JSON (Task 7), decision-record source (Tasks 1, 9), no-duplication on replay (Task 9), evidence-ledger traceability (structurally guaranteed - replay artifacts embed the untouched `WorkflowResult.evidence_ledger`), end-to-end test coverage across all six named failure/success paths for both plain and chat-first surfaces (Task 11).
- **Placeholder scan:** Task 2's Step 5 code block intentionally contains placeholder helper names, explicitly flagged and corrected in Step 6 before the task is considered done - not left in the final file. Task 9's tests intentionally defer to the real, unseen contents of `tests/test_decisions_service.py` rather than guessing its fixture names - the step explicitly instructs reading the file first.
- **Type consistency:** `ReplayArtifact.chat_response: ChatResponse`, `run_replay_portfolio_workflow(...) -> WorkflowResult`, and `ResultSource` are used identically everywhere they're referenced across tasks.
