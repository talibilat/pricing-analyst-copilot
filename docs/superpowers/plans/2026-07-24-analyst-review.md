# Add Meaningful Analyst Review and a Versioned Decision Record Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the human decision stage to the controlled-increase workflow from #4. A pricing analyst can approve, approve with conditions, reject, or request further investigation on a recommendation; the decision is validated (rationale always required, conditions required for approve-with-conditions and request-investigation), persisted to local SQLite with full context (portfolio selection, recommendation snapshot, governance outcome, evidence IDs, configuration versions), and retrievable through the same service boundary used by the API and Streamlit.

**Architecture:** `AnalystDecision` (already scaffolded as an empty contract in #2) becomes the full decision record, embedding the reviewed `PortfolioQuestion`, `Recommendation`, and `GovernanceOutcome` snapshots plus a new `ConfigurationVersions` block, with a `model_validator` enforcing the material-decision rules. A `DecisionStore` (SQLite, one row per decision, full JSON payload plus indexed columns) persists and retrieves records. `record_analyst_decision()` is the single service-boundary function both the FastAPI routes and Streamlit call - no separate logic paths. Nothing in this ticket touches pricing, rating, or the portfolio dataset; the store is purely additive local storage.

**Tech Stack:** Adds Python's stdlib `sqlite3` (no new dependency) to the existing stack.

## Global Constraints

- Four analyst actions only: approve, approve with conditions, reject, request investigation (the `AnalystDecisionType` enum from #2 - unchanged).
- A material decision (any of the four) cannot be submitted without a non-empty rationale.
- Approve-with-conditions and request-investigation require at least one non-empty entry in `conditions` (conditions and outstanding-questions/required-evidence share the same field: both are "follow-up items attached to the decision").
- The stored record includes: portfolio selection, recommendation version, governance version, evidence IDs, analyst action, rationale, conditions, timestamp, and configuration versions (model name, scenario seed/version, policy movement limit) - all in one persisted object, not scattered across tables.
- Decision records persist in local SQLite (stdlib `sqlite3`, no new dependency) and are retrievable through `record_analyst_decision`'s sibling read functions - the same service boundary already used by API/CLI/Streamlit.
- The interface must visually and textually distinguish "system recommendation" from "analyst decision" - never implies the analyst's review *is* the recommendation, and never uses language implying a price was changed.
- No code path in this ticket calls, imports, or invokes any pricing/rating/policy-writing mechanism - there is none in this codebase, and a test proves recording a decision never changes subsequent deterministic workflow output.
- Fair-value status and investigation areas (from #4) stay visible during the review step, not hidden behind it.

---

## File Structure

```
.gitignore                                          # MODIFY: ignore var/ (local SQLite files)
src/pricing_copilot/config.py                       # MODIFY: add decision_store_path setting
src/pricing_copilot/contracts.py                    # MODIFY: extend AnalystDecision, add ConfigurationVersions, DecisionRequest
src/pricing_copilot/recommendation/synthesizer.py    # MODIFY: add RECOMMENDATION_VERSION constant
src/pricing_copilot/recommendation/governance.py     # MODIFY: add GOVERNANCE_VERSION constant
src/pricing_copilot/decisions/__init__.py
src/pricing_copilot/decisions/store.py               # DecisionStore (SQLite)
src/pricing_copilot/decisions/service.py             # record_analyst_decision, get_decision_store
src/pricing_copilot/api.py                           # MODIFY: POST /decisions, GET /decisions/{id}, GET /decisions
src/pricing_copilot/streamlit_app.py                 # MODIFY: session_state refactor + review form + decision history
tests/test_decisions_contracts.py
tests/test_decisions_store.py
tests/test_decisions_service.py
tests/test_api.py                                    # MODIFY: decision endpoints + no-mutation proof
tests/test_streamlit_copy.py
```

**Interfaces summary:**
- `contracts.py` gains: `ConfigurationVersions` (model_name, recommendation_version, governance_version, scenario_seed, scenario_version, max_price_movement_pct); `AnalystDecision` extended with `record_id: str | None`, `question: PortfolioQuestion`, `recommendation: Recommendation`, `governance_outcome: GovernanceOutcome`, `evidence_ids: list[str]`, `configuration_versions: ConfigurationVersions`, plus a `model_validator` enforcing rationale/conditions rules; `DecisionRequest` (question, recommendation, governance_outcome, decision, rationale, conditions).
- `recommendation/synthesizer.py` gains: `RECOMMENDATION_VERSION = "single-agent-baseline-v1"`.
- `recommendation/governance.py` gains: `GOVERNANCE_VERSION = "deterministic-governance-v1"`.
- `decisions/store.py` exports: `DecisionStore` with `from_path(path) -> DecisionStore`, `save(decision) -> None`, `get(record_id) -> AnalystDecision | None`, `list_for_question(product, region, segment) -> list[AnalystDecision]`.
- `decisions/service.py` exports: `record_analyst_decision(request: DecisionRequest, settings: Settings, store: DecisionStore) -> AnalystDecision`, `get_decision_store() -> DecisionStore` (cached, reads `settings.decision_store_path`).

---

## Task 1: Settings and gitignore

**Files:** Modify `src/pricing_copilot/config.py`, `.gitignore`.

- [ ] **Step 1: Add the decision store path setting**

In `src/pricing_copilot/config.py`, add a field to `Settings` (after `policy: PolicySettings = PolicySettings()`):
```python
    decision_store_path: str = "var/decisions.sqlite3"
```

- [ ] **Step 2: Ignore local SQLite storage**

Add to `.gitignore`:
```
var/
```

- [ ] **Step 3: Commit**

```bash
git add src/pricing_copilot/config.py .gitignore
git commit -m "chore: add decision store path setting"
```

---

## Task 2: Extend contracts - ConfigurationVersions, AnalystDecision, DecisionRequest

**Files:** Modify `src/pricing_copilot/contracts.py`; Test: `tests/test_decisions_contracts.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_decisions_contracts.py
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecision,
    AnalystDecisionType,
    ConfigurationVersions,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)


def _question() -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)),
        scenario=None,
    )


def _versions() -> ConfigurationVersions:
    return ConfigurationVersions(
        model_name="gpt-5.4",
        recommendation_version="single-agent-baseline-v1",
        governance_version="deterministic-governance-v1",
        scenario_seed=20260101,
        scenario_version="v1",
        max_price_movement_pct=5.0,
    )


def _base_kwargs() -> dict:
    return dict(
        question=_question(),
        recommendation=Recommendation(action=RecommendationAction.INCREASE, rationale="test"),
        governance_outcome=GovernanceOutcome(approved=True),
        evidence_ids=["claims-north_west-2025-12-01"],
        configuration_versions=_versions(),
        decided_at=datetime.now(UTC),
    )


def test_approve_requires_no_conditions() -> None:
    decision = AnalystDecision(
        decision=AnalystDecisionType.APPROVE, rationale="Evidence is sufficient.", **_base_kwargs()
    )
    assert decision.conditions == []


def test_reject_requires_no_conditions() -> None:
    decision = AnalystDecision(
        decision=AnalystDecisionType.REJECT, rationale="Not convinced by the evidence.", **_base_kwargs()
    )
    assert decision.decision is AnalystDecisionType.REJECT


def test_empty_rationale_is_rejected() -> None:
    with pytest.raises(ValidationError, match="rationale is required"):
        AnalystDecision(decision=AnalystDecisionType.APPROVE, rationale="   ", **_base_kwargs())


def test_approve_with_conditions_requires_conditions() -> None:
    with pytest.raises(ValidationError, match="requires at least one"):
        AnalystDecision(
            decision=AnalystDecisionType.APPROVE_WITH_CONDITIONS,
            rationale="Approve but constrain rollout.",
            conditions=[],
            **_base_kwargs(),
        )


def test_approve_with_conditions_accepts_explicit_conditions() -> None:
    decision = AnalystDecision(
        decision=AnalystDecisionType.APPROVE_WITH_CONDITIONS,
        rationale="Approve but constrain rollout.",
        conditions=["Limit to pilot cohort for the first cycle."],
        **_base_kwargs(),
    )
    assert decision.conditions == ["Limit to pilot cohort for the first cycle."]


def test_request_investigation_requires_outstanding_questions() -> None:
    with pytest.raises(ValidationError, match="requires at least one"):
        AnalystDecision(
            decision=AnalystDecisionType.REQUEST_INVESTIGATION,
            rationale="Need more evidence before deciding.",
            conditions=[],
            **_base_kwargs(),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decisions_contracts.py -v`
Expected: FAIL - `ConfigurationVersions` does not exist yet, `AnalystDecision` doesn't accept these fields.

- [ ] **Step 3: Extend `contracts.py`**

Add `ConfigurationVersions` (after `GovernanceOutcome`):
```python
class ConfigurationVersions(BaseModel):
    model_name: str
    recommendation_version: str
    governance_version: str
    scenario_seed: int
    scenario_version: str
    max_price_movement_pct: float
```

Replace the existing (currently minimal) `AnalystDecision` class with:
```python
class AnalystDecision(BaseModel):
    record_id: str | None = None
    question: PortfolioQuestion
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    evidence_ids: list[str] = Field(default_factory=list)
    decision: AnalystDecisionType
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    decided_at: datetime
    configuration_versions: ConfigurationVersions

    @model_validator(mode="after")
    def check_material_decision_requirements(self) -> "AnalystDecision":
        if not self.rationale.strip():
            raise ValueError("rationale is required for a material analyst decision.")
        needs_conditions = self.decision in (
            AnalystDecisionType.APPROVE_WITH_CONDITIONS,
            AnalystDecisionType.REQUEST_INVESTIGATION,
        )
        if needs_conditions and not any(c.strip() for c in self.conditions):
            raise ValueError(
                f"{self.decision.value} requires at least one recorded condition or "
                "outstanding question."
            )
        return self


class DecisionRequest(BaseModel):
    question: PortfolioQuestion
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    decision: AnalystDecisionType
    rationale: str
    conditions: list[str] = Field(default_factory=list)
```

`AnalystDecision` must be defined **after** `Recommendation` and `GovernanceOutcome` in the file (it already is, per the existing class order) - no import changes needed since everything referenced is already defined earlier in `contracts.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decisions_contracts.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest -v`
Expected: all still pass - `AnalystDecision` was unused elsewhere in the codebase before this ticket, so no other call site breaks.

- [ ] **Step 6: Commit**

```bash
git add src/pricing_copilot/contracts.py tests/test_decisions_contracts.py
git commit -m "feat: extend AnalystDecision into a full versioned decision record"
```

---

## Task 3: Version constants on the recommendation pipeline

**Files:** Modify `src/pricing_copilot/recommendation/synthesizer.py`, `src/pricing_copilot/recommendation/governance.py`.

- [ ] **Step 1: Add `RECOMMENDATION_VERSION`**

In `src/pricing_copilot/recommendation/synthesizer.py`, add near the top (after imports, before `SYSTEM_PROMPT`):
```python
RECOMMENDATION_VERSION = "single-agent-baseline-v1"
```

- [ ] **Step 2: Add `GOVERNANCE_VERSION`**

In `src/pricing_copilot/recommendation/governance.py`, add near the top (after imports, before `_NUMBER_PATTERN`):
```python
GOVERNANCE_VERSION = "deterministic-governance-v1"
```

- [ ] **Step 3: Verify imports still resolve**

Run: `uv run python -c "from pricing_copilot.recommendation.synthesizer import RECOMMENDATION_VERSION; from pricing_copilot.recommendation.governance import GOVERNANCE_VERSION; print(RECOMMENDATION_VERSION, GOVERNANCE_VERSION)"`

- [ ] **Step 4: Commit**

```bash
git add src/pricing_copilot/recommendation/synthesizer.py src/pricing_copilot/recommendation/governance.py
git commit -m "feat: version the recommendation synthesis and governance stages"
```

---

## Task 4: SQLite-backed decision store

**Files:** Create `src/pricing_copilot/decisions/__init__.py`, `src/pricing_copilot/decisions/store.py`; Test: `tests/test_decisions_store.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_decisions_store.py
from datetime import UTC, date, datetime
from pathlib import Path

from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecision,
    AnalystDecisionType,
    ConfigurationVersions,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)
from pricing_copilot.decisions.store import DecisionStore


def _decision(region: Region = Region.NORTH_WEST) -> AnalystDecision:
    return AnalystDecision(
        record_id="11111111-1111-1111-1111-111111111111",
        question=PortfolioQuestion(
            product=Product.PERSONAL_MOTOR,
            region=region,
            segment=Segment.RENEWAL,
            analysis_period=AnalysisPeriod(
                start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)
            ),
            scenario=None,
        ),
        recommendation=Recommendation(action=RecommendationAction.INCREASE, rationale="test"),
        governance_outcome=GovernanceOutcome(approved=True),
        evidence_ids=["claims-north_west-2025-12-01"],
        decision=AnalystDecisionType.APPROVE,
        rationale="Evidence supports the recommendation.",
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        configuration_versions=ConfigurationVersions(
            model_name="gpt-5.4",
            recommendation_version="single-agent-baseline-v1",
            governance_version="deterministic-governance-v1",
            scenario_seed=20260101,
            scenario_version="v1",
            max_price_movement_pct=5.0,
        ),
    )


def test_save_and_get_round_trips_exactly(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    decision = _decision()
    store.save(decision)

    loaded = store.get(decision.record_id)
    assert loaded == decision


def test_get_unknown_id_returns_none(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    assert store.get("does-not-exist") is None


def test_list_for_question_filters_by_portfolio(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    nw = _decision(region=Region.NORTH_WEST).model_copy(update={"record_id": "nw-1"})
    se = _decision(region=Region.SOUTH_EAST).model_copy(update={"record_id": "se-1"})
    store.save(nw)
    store.save(se)

    results = store.list_for_question(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    assert [r.record_id for r in results] == ["nw-1"]


def test_decisions_persist_across_store_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "decisions.sqlite3"
    DecisionStore.from_path(db_path).save(_decision())

    reopened = DecisionStore.from_path(db_path)
    assert reopened.get("11111111-1111-1111-1111-111111111111") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decisions_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.decisions.store'`

- [ ] **Step 3: Implement**

```python
# src/pricing_copilot/decisions/__init__.py
"""Analyst decision recording: SQLite-backed persistence and the recording service."""
```

```python
# src/pricing_copilot/decisions/store.py
from __future__ import annotations

import sqlite3
from pathlib import Path

from pricing_copilot.contracts import AnalystDecision, Product, Region, Segment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    record_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    region TEXT NOT NULL,
    segment TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


class DecisionStore:
    """Local SQLite persistence for analyst decision records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.execute(_SCHEMA)
        self._connection.commit()

    @classmethod
    def from_path(cls, path: Path) -> "DecisionStore":
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path))
        return cls(connection)

    def save(self, decision: AnalystDecision) -> None:
        if decision.record_id is None:
            raise ValueError("Cannot save a decision without a record_id.")
        self._connection.execute(
            "INSERT OR REPLACE INTO decisions "
            "(record_id, product, region, segment, decision, decided_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                decision.record_id,
                decision.question.product.value,
                decision.question.region.value,
                decision.question.segment.value,
                decision.decision.value,
                decision.decided_at.isoformat(),
                decision.model_dump_json(),
            ),
        )
        self._connection.commit()

    def get(self, record_id: str) -> AnalystDecision | None:
        row = self._connection.execute(
            "SELECT payload FROM decisions WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        return AnalystDecision.model_validate_json(row[0])

    def list_for_question(
        self, product: Product, region: Region, segment: Segment
    ) -> list[AnalystDecision]:
        rows = self._connection.execute(
            "SELECT payload FROM decisions WHERE product = ? AND region = ? AND segment = ? "
            "ORDER BY decided_at DESC",
            (product.value, region.value, segment.value),
        ).fetchall()
        return [AnalystDecision.model_validate_json(row[0]) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decisions_store.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/decisions/__init__.py src/pricing_copilot/decisions/store.py tests/test_decisions_store.py
git commit -m "feat: add SQLite-backed decision store"
```

---

## Task 5: Decision recording service

**Files:** Create `src/pricing_copilot/decisions/service.py`; Test: `tests/test_decisions_service.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_decisions_service.py
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from pricing_copilot.config import Settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecisionType,
    DecisionRequest,
    GovernanceOutcome,
    PortfolioQuestion,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)
from pricing_copilot.decisions.service import record_analyst_decision
from pricing_copilot.decisions.store import DecisionStore


def _request(decision: AnalystDecisionType, rationale: str, conditions: list[str] | None = None) -> DecisionRequest:
    return DecisionRequest(
        question=PortfolioQuestion(
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            analysis_period=AnalysisPeriod(
                start_month=date(2024, 1, 1), end_month=date(2025, 12, 1)
            ),
            scenario=None,
        ),
        recommendation=Recommendation(
            action=RecommendationAction.INCREASE,
            rationale="test",
            cited_evidence_ids=["claims-north_west-2025-12-01"],
        ),
        governance_outcome=GovernanceOutcome(approved=True),
        decision=decision,
        rationale=rationale,
        conditions=conditions or [],
    )


def test_record_decision_persists_and_returns_full_record(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    settings = Settings()

    recorded = record_analyst_decision(
        _request(AnalystDecisionType.APPROVE, "Evidence supports the recommendation."),
        settings,
        store,
    )

    assert recorded.record_id is not None
    assert recorded.evidence_ids == ["claims-north_west-2025-12-01"]
    assert recorded.configuration_versions.model_name == settings.model_name
    assert recorded.configuration_versions.max_price_movement_pct == settings.policy.max_price_movement_pct
    assert store.get(recorded.record_id) == recorded


def test_record_decision_rejects_missing_rationale(tmp_path: Path) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    with pytest.raises(ValidationError, match="rationale is required"):
        record_analyst_decision(
            _request(AnalystDecisionType.APPROVE, "   "), Settings(), store
        )


def test_record_decision_rejects_conditions_missing_for_approve_with_conditions(
    tmp_path: Path,
) -> None:
    store = DecisionStore.from_path(tmp_path / "decisions.sqlite3")
    with pytest.raises(ValidationError, match="requires at least one"):
        record_analyst_decision(
            _request(AnalystDecisionType.APPROVE_WITH_CONDITIONS, "Approve but constrain."),
            Settings(),
            store,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decisions_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.decisions.service'`

- [ ] **Step 3: Implement**

```python
# src/pricing_copilot/decisions/service.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import AnalystDecision, ConfigurationVersions, DecisionRequest
from pricing_copilot.data.generation import DEFAULT_SCENARIO_SEED, DEFAULT_SCENARIO_VERSION
from pricing_copilot.decisions.store import DecisionStore
from pricing_copilot.recommendation.governance import GOVERNANCE_VERSION
from pricing_copilot.recommendation.synthesizer import RECOMMENDATION_VERSION


def record_analyst_decision(
    request: DecisionRequest, settings: Settings, store: DecisionStore
) -> AnalystDecision:
    configuration_versions = ConfigurationVersions(
        model_name=settings.model_name,
        recommendation_version=RECOMMENDATION_VERSION,
        governance_version=GOVERNANCE_VERSION,
        scenario_seed=DEFAULT_SCENARIO_SEED,
        scenario_version=DEFAULT_SCENARIO_VERSION,
        max_price_movement_pct=settings.policy.max_price_movement_pct,
    )
    decision = AnalystDecision(
        record_id=str(uuid.uuid4()),
        question=request.question,
        recommendation=request.recommendation,
        governance_outcome=request.governance_outcome,
        evidence_ids=request.recommendation.cited_evidence_ids,
        decision=request.decision,
        rationale=request.rationale,
        conditions=request.conditions,
        decided_at=datetime.now(UTC),
        configuration_versions=configuration_versions,
    )
    store.save(decision)
    return decision


@lru_cache
def get_decision_store() -> DecisionStore:
    settings = get_settings()
    return DecisionStore.from_path(Path(settings.decision_store_path))
```

Note: `record_analyst_decision` raises `pydantic.ValidationError` directly from constructing `AnalystDecision` (its `model_validator` runs at construction time) - callers (API, Streamlit) catch this the same way `/workflow` already catches `UnsupportedPortfolioError`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decisions_service.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/decisions/service.py tests/test_decisions_service.py
git commit -m "feat: add analyst decision recording service"
```

---

## Task 6: API endpoints and no-mutation proof

**Files:** Modify `src/pricing_copilot/api.py`, `tests/test_api.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py`:
```python
def _controlled_increase_payload() -> dict:
    return {
        "product": "personal_motor",
        "region": "north_west",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": "controlled_increase",
    }


def _run_controlled_increase(monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(
        "pricing_copilot.workflow.get_default_synthesizer",
        lambda settings: FakeRecommendationSynthesizer(),
    )
    response = client.post("/workflow", json=_controlled_increase_payload())
    assert response.status_code == 200
    return response.json()


def test_post_decisions_approve_persists_and_is_retrievable(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_result = _run_controlled_increase(monkeypatch)
    payload = {
        "question": workflow_result["question"],
        "recommendation": workflow_result["recommendation"],
        "governance_outcome": workflow_result["governance_outcome"],
        "decision": "approve",
        "rationale": "Evidence and citations are sufficient to approve.",
        "conditions": [],
    }
    response = client.post("/decisions", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["record_id"]
    assert body["decision"] == "approve"

    fetched = client.get(f"/decisions/{body['record_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["record_id"] == body["record_id"]


def test_post_decisions_rejects_missing_rationale(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_result = _run_controlled_increase(monkeypatch)
    payload = {
        "question": workflow_result["question"],
        "recommendation": workflow_result["recommendation"],
        "governance_outcome": workflow_result["governance_outcome"],
        "decision": "approve",
        "rationale": "   ",
        "conditions": [],
    }
    response = client.post("/decisions", json=payload)
    assert response.status_code == 422


def test_post_decisions_approve_with_conditions_requires_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_result = _run_controlled_increase(monkeypatch)
    payload = {
        "question": workflow_result["question"],
        "recommendation": workflow_result["recommendation"],
        "governance_outcome": workflow_result["governance_outcome"],
        "decision": "approve_with_conditions",
        "rationale": "Approve but constrain the rollout.",
        "conditions": [],
    }
    response = client.post("/decisions", json=payload)
    assert response.status_code == 422


def test_get_decisions_unknown_id_returns_404() -> None:
    response = client.get("/decisions/does-not-exist")
    assert response.status_code == 404


def test_recording_a_decision_never_mutates_subsequent_workflow_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _run_controlled_increase(monkeypatch)
    payload = {
        "question": before["question"],
        "recommendation": before["recommendation"],
        "governance_outcome": before["governance_outcome"],
        "decision": "reject",
        "rationale": "Not convinced the evidence supports action yet.",
        "conditions": [],
    }
    decision_response = client.post("/decisions", json=payload)
    assert decision_response.status_code == 200

    after = _run_controlled_increase(monkeypatch)
    assert after["analytics"] == before["analytics"]
    assert after["recommendation"]["action"] == before["recommendation"]["action"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL - `/decisions` routes don't exist (404 for POST, not the expected status codes).

- [ ] **Step 3: Add the routes to `api.py`**

Add imports (with the existing imports):
```python
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import AnalystDecision, DecisionRequest
from pricing_copilot.decisions.service import get_decision_store, record_analyst_decision
```
(`get_settings` may already be imported indirectly via `workflow.py` usage - check and avoid a duplicate import if `api.py` already imports it.)

Add the routes at the end of `api.py`:
```python
@app.post("/decisions", response_model=AnalystDecision)
def submit_decision(request: DecisionRequest) -> AnalystDecision:
    try:
        return record_analyst_decision(request, get_settings(), get_decision_store())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/decisions/{record_id}", response_model=AnalystDecision)
def fetch_decision(record_id: str) -> AnalystDecision:
    decision = get_decision_store().get(record_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision record found for id {record_id}.")
    return decision
```
Add `from pydantic import ValidationError` to the imports if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (all tests including the new decision ones). The no-mutation test passes because `run_portfolio_workflow` reads from a freshly-generated in-memory DuckDB dataset every call (from #3) and the decision store is a completely separate SQLite file - there is no shared mutable state between them.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/api.py tests/test_api.py
git commit -m "feat: expose analyst decision recording and retrieval through the API"
```

---

## Task 7: Streamlit review form (session-state refactor)

**Files:** Modify `src/pricing_copilot/streamlit_app.py`; Test: `tests/test_streamlit_copy.py`.

Streamlit reruns the whole script on every widget interaction. A second form (the review form) submitting must not lose the first form's (`portfolio_question`) result - so the workflow result moves into `st.session_state` instead of a plain local variable scoped to `if submitted:`.

- [ ] **Step 1: Write the copy-guard test first**

```python
# tests/test_streamlit_copy.py
from pathlib import Path

BANNED_PHRASES = [
    "price updated",
    "price has been updated",
    "price change executed",
    "pricing action executed",
]

SOURCE = Path("src/pricing_copilot/streamlit_app.py").read_text().lower()


def test_streamlit_app_never_claims_a_price_was_executed() -> None:
    for phrase in BANNED_PHRASES:
        assert phrase not in SOURCE, f"Found banned phrase: {phrase!r}"


def test_streamlit_app_distinguishes_recommendation_from_decision() -> None:
    assert "system recommendation" in SOURCE
    assert "analyst decision" in SOURCE or "analyst review" in SOURCE
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_streamlit_copy.py -v`
Expected: the second test fails until Step 3's copy changes land (first test trivially passes since no banned phrase exists yet - that's fine, it's a regression guard, not currently red).

- [ ] **Step 3: Rewrite the result-rendering section of `streamlit_app.py`**

Replace everything from `if submitted:` to the end of the file with:

```python
if submitted:
    if (
        not isinstance(product, Product)
        or not isinstance(region, Region)
        or not isinstance(segment, Segment)
    ):
        raise TypeError("Product, region, and segment selectors must always return a value.")

    try:
        question = PortfolioQuestion(
            product=product,
            region=region,
            segment=segment,
            analysis_period=AnalysisPeriod(start_month=start_month, end_month=end_month),
            scenario=scenario_choice,
        )
        result = run_portfolio_workflow(question)
    except UnsupportedPortfolioError as exc:
        st.error(str(exc))
        st.session_state.pop("workflow_result", None)
        st.session_state.pop("portfolio_question", None)
    else:
        st.session_state["workflow_result"] = result
        st.session_state["portfolio_question"] = question
        st.session_state.pop("decision_confirmation", None)

result = st.session_state.get("workflow_result")
question = st.session_state.get("portfolio_question")

if result is not None and question is not None:
    st.subheader("System recommendation")
    st.write(f"**{result.recommendation.action.value}**")
    st.write(result.recommendation.rationale)

    if result.analytics is not None:
        analytics = result.analytics

        st.subheader("Loss ratio (%)")
        st.line_chart(
            {"loss_ratio_pct": [v.value * 100 for v in analytics.claims.loss_ratio.monthly]}
        )

        st.subheader("Claim severity (GBP)")
        st.line_chart(
            {
                "average_severity_gbp": [
                    v.value for v in analytics.claims.average_severity_gbp.monthly
                ]
            }
        )

        st.subheader("Conversion and retention (%)")
        st.line_chart(
            {
                "quote_to_sale_conversion_pct": [
                    v.value * 100 for v in analytics.conversion.quote_to_sale_conversion.monthly
                ],
                "renewal_retention_pct": [
                    v.value * 100 for v in analytics.conversion.renewal_retention.monthly
                ],
            }
        )

        st.subheader("Competitor price-index movement")
        st.line_chart(
            {
                movement.competitor_name: [v.value for v in movement.price_index.monthly]
                for movement in analytics.competitors.competitors
            }
        )

        recommendation = result.recommendation
        st.subheader("Proposed action")
        if recommendation.price_range is not None:
            st.write(
                f"**{recommendation.action.value}** "
                f"({recommendation.price_range.lower_pct:g}% to "
                f"{recommendation.price_range.upper_pct:g}%)"
            )
        else:
            st.write(f"**{recommendation.action.value}**")

        evidence_col, counter_col = st.columns(2)
        with evidence_col:
            st.markdown("**Supporting rationale**")
            st.write(recommendation.rationale)
        with counter_col:
            st.markdown("**Counter-evidence**")
            for item in recommendation.counter_evidence:
                st.write(f"- {item}")

        if recommendation.conditions:
            st.markdown("**Conditions**")
            for item in recommendation.conditions:
                st.write(f"- {item}")
        if recommendation.investigation_areas:
            st.markdown("**Areas for further investigation**")
            for item in recommendation.investigation_areas:
                st.write(f"- {item}")

        if recommendation.fair_value_status is not None:
            st.subheader(f"Fair-value status: {recommendation.fair_value_status.value}")
            for item in recommendation.fair_value_follow_up:
                st.write(f"- {item}")

        if recommendation.confidence is not None:
            st.subheader("Confidence components")
            st.json(recommendation.confidence.model_dump())

        with st.expander("Evidence ledger detail"):
            if result.evidence_ledger is not None:
                for entry in result.evidence_ledger.entries:
                    st.write(
                        f"- **{entry.evidence_id}** ({entry.source_type}): "
                        f"{entry.interpretation}"
                    )

        st.subheader("Pricing history")
        for action in analytics.pricing_history:
            st.write(
                f"- **{action.period.isoformat()}**: {action.price_change_pct:+.1f}% - "
                f"{action.rationale} (conversion impact {action.conversion_impact_pct:+.1f}%, "
                f"loss-ratio impact {action.loss_ratio_impact_pct:+.1f}%)"
            )

        st.subheader("Analyst review")
        st.caption(
            "This section records the analyst's decision. It does not change the system "
            "recommendation shown above, and it never executes a pricing change."
        )
        with st.form("analyst_review"):
            decision_choice = st.selectbox(
                "Decision",
                options=list(AnalystDecisionType),
                format_func=lambda d: d.value,
            )
            rationale_input = st.text_area("Rationale (required for every decision)")
            conditions_input = st.text_area(
                "Conditions or outstanding questions - one per line. Required for "
                "'approve_with_conditions' and 'request_investigation'."
            )
            decision_submitted = st.form_submit_button("Record analyst decision")

        if decision_submitted:
            conditions_list = [line.strip() for line in conditions_input.splitlines() if line.strip()]
            request = DecisionRequest(
                question=question,
                recommendation=result.recommendation,
                governance_outcome=result.governance_outcome,
                decision=decision_choice,
                rationale=rationale_input,
                conditions=conditions_list,
            )
            try:
                recorded = record_analyst_decision(
                    request, get_settings(), get_decision_store()
                )
            except ValidationError as exc:
                st.error(f"Cannot record decision: {exc}")
            else:
                st.session_state["decision_confirmation"] = recorded

        confirmation = st.session_state.get("decision_confirmation")
        if confirmation is not None:
            st.success(
                f"Analyst decision recorded: **{confirmation.decision.value}** "
                f"(record id `{confirmation.record_id}`)."
            )

        with st.expander("Decision history for this portfolio"):
            history = get_decision_store().list_for_question(
                question.product, question.region, question.segment
            )
            if not history:
                st.write("No recorded decisions yet for this portfolio.")
            for record in history:
                st.write(
                    f"- **{record.decision.value}** at {record.decided_at.isoformat()} "
                    f"- {record.rationale}"
                )
    else:
        st.subheader("Missing evidence")
        for item in result.missing_evidence:
            st.warning(f"**{item.domain.value}**: {item.reason}")

    st.subheader("Specialist reports")
    for report in result.specialist_reports:
        st.write(f"- **{report.domain.value}** ({report.status}): {report.summary}")

    st.subheader("Governance outcome")
    st.json(result.governance_outcome.model_dump())
```

- [ ] **Step 4: Update the imports at the top of `streamlit_app.py`**

Replace the import block with:
```python
from __future__ import annotations

from datetime import date

import streamlit as st
from pydantic import ValidationError

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecisionType,
    DecisionRequest,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.decisions.service import get_decision_store, record_analyst_decision
from pricing_copilot.workflow import run_portfolio_workflow
```

- [ ] **Step 5: Run the copy-guard test**

Run: `uv run pytest tests/test_streamlit_copy.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Manually verify it boots and the review flow works**

Run: `uv run streamlit run src/pricing_copilot/streamlit_app.py --server.headless true --server.port 8506 &`, wait, `curl -sf http://localhost:8506 > /dev/null && echo OK`, stop the server. Then, in a real interactive check (browser tooling), select `controlled_increase`, run the analysis, fill in a rationale, submit each of the four decision types once and confirm: a confirmation message appears distinct from the system recommendation, `approve_with_conditions` and `request_investigation` are rejected with an inline error when conditions are left blank, and the "Decision history" expander shows the recorded entries. If the custom BaseWeb scenario selectbox is hard to drive via low-level clicks, prefer `form_input` with the target value (typing filters the option list) followed by clicking the filtered row, or fall back to trusting the automated `test_api.py` coverage for the same code path plus a plain page-boot check here - do not treat that as a project bug.

- [ ] **Step 7: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py tests/test_streamlit_copy.py
git commit -m "feat: add analyst review form and decision history to Streamlit"
```

---

## Task 8: Full verification pass

- [ ] **Step 1: Run the full quality command**

Run: `./scripts/quality.sh`
Expected: Ruff, MyPy strict, Pytest, Bandit, and the secret scan all pass.

- [ ] **Step 2: Manual smoke test of the API decision flow**

```bash
uv run uvicorn pricing_copilot.api:app --port 8000 &
```
Run the controlled-increase `/workflow` call from the #4 README pattern, capture the `question`/`recommendation`/`governance_outcome` from the response, then:
```bash
curl -s -X POST http://127.0.0.1:8000/decisions \
  -H "Content-Type: application/json" \
  -d '{"question": ..., "recommendation": ..., "governance_outcome": ..., "decision": "approve_with_conditions", "rationale": "Approve for a pilot cohort only.", "conditions": ["Limit to pilot cohort for the first renewal cycle."]}'
```
Expected: 200 with a `record_id`, then `GET /decisions/{record_id}` returns the same record.

- [ ] **Step 3: Confirm #2/#3/#4 behavior is untouched**

Run: `uv run pytest tests/test_workflow.py tests/test_recommendation_live.py -v` (the live test runs for real since credentials are configured in this environment).
Expected: all pass unchanged - this ticket adds a new, separate persistence layer and never modifies `workflow.py`, `analytics/`, or `recommendation/synthesizer.py`'s core logic.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve quality command findings"
```
