# Bootstrap the Governed Workflow and Quality Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first runnable vertical slice of the Pricing Decision Copilot: a pricing analyst can submit the North West personal motor renewal portfolio question through a stable service boundary (shared by API, CLI, and Streamlit) and receive a typed, safe `investigate` outcome, because no evidence has been loaded yet. This ticket also establishes the repository's quality baseline.

**Architecture:** A single Python package (`pricing_copilot`) exposes one service-boundary function, `run_portfolio_workflow`, that validates a typed `PortfolioQuestion` against a supported-portfolio catalog and returns a typed `WorkflowResult` containing specialist reports, a recommendation, a governance outcome, and any missing evidence. Three thin adapters (FastAPI route, CLI command, Streamlit page) all call this same function so there is exactly one workflow implementation. No LLM calls, no data sources, and no pricing-execution mechanism exist yet - this ticket only proves the governed shape of the workflow and that it safely abstains.

**Tech Stack:** Python 3.12, uv, Pydantic v2, pydantic-settings, FastAPI, Streamlit, Pytest, Ruff, MyPy (strict), Bandit, httpx (for FastAPI TestClient).

## Global Constraints

- Python 3.12 and uv with reproducible dependency resolution (committed `uv.lock`).
- The application must start through documented API, CLI, and Streamlit entry points, all calling the same service-boundary function.
- Supported portfolio selection = product + region + segment + analysis period + optional scenario.
- Unsupported/invalid combinations are rejected with a clear user-facing explanation (never a raw stack trace).
- The initial workflow always returns `investigate` with explicit missing-evidence reasons; it must never fabricate a recommendation, since no evidence sources are connected yet.
- Typed contracts must cover: portfolio questions, evidence items, specialist reports, recommendations, governance outcomes, and analyst decisions.
- Recommendation vocabulary is exactly `increase | decrease | hold | investigate`.
- Price ranges are represented explicitly (not implied by prose) and the policy movement limit (5%) is a configuration value, never a prompt string.
- Model name and runtime settings (timeout, turn limits) are configurable via environment/settings, with no code path hardcoding a single model.
- Nothing in the codebase may execute a pricing change - no mutation of any pricing system anywhere.
- One quality command runs Ruff, MyPy, Pytest, and Bandit.
- A secret-scanning check and a safe `.env.example` are provided.
- The primary end-to-end test exercises the public workflow seam (`run_portfolio_workflow` / the FastAPI route), not internals.
- README setup instructions must be sufficient for a new developer to run the safe-abstention workflow.

---

## File Structure

```
pyproject.toml                              # uv project, deps, tool config (ruff/mypy/pytest/bandit)
.env.example                                # safe example env vars
.gitignore
scripts/quality.sh                          # single quality command
scripts/check_secrets.py                    # secret-scanning check
src/pricing_copilot/__init__.py
src/pricing_copilot/contracts.py            # all typed contracts (Pydantic models + enums)
src/pricing_copilot/catalog.py              # supported portfolio catalog + validation error
src/pricing_copilot/config.py               # Settings (pydantic-settings) incl. policy limits
src/pricing_copilot/workflow.py             # run_portfolio_workflow (the service boundary)
src/pricing_copilot/api.py                  # FastAPI app
src/pricing_copilot/cli.py                  # CLI entry point
src/pricing_copilot/streamlit_app.py        # Streamlit UI
tests/__init__.py
tests/test_catalog.py
tests/test_workflow.py                      # primary e2e seam test
tests/test_api.py
tests/test_cli.py
tests/test_check_secrets.py
README.md                                   # append setup/run instructions
```

**Interfaces summary (for cross-task reference):**
- `contracts.py` exports: `Product`, `Region`, `Segment`, `ScenarioName`, `EvidenceDomain`, `AnalysisPeriod`, `PortfolioQuestion`, `MissingEvidence`, `SpecialistReport`, `RecommendationAction`, `PriceRange`, `Recommendation`, `GovernanceOutcome`, `AnalystDecisionType`, `AnalystDecision`, `WorkflowResult`.
- `catalog.py` exports: `UnsupportedPortfolioError`, `validate_portfolio_combination(product, region, segment) -> None`.
- `config.py` exports: `PolicySettings`, `Settings`, `get_settings() -> Settings`.
- `workflow.py` exports: `run_portfolio_workflow(question: PortfolioQuestion, settings: Settings | None = None) -> WorkflowResult`.

---

## Task 1: Project scaffold (uv, tooling config, env example)

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/pricing_copilot/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: an importable `pricing_copilot` package under `src/`, and dev tooling (`ruff`, `mypy`, `pytest`, `bandit`, `httpx`) available via `uv run`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "pricing-copilot"
version = "0.1.0"
description = "Governed Pricing Decision Copilot prototype"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "streamlit>=1.36",
]

[project.scripts]
pricing-copilot = "pricing_copilot.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pricing_copilot"]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "ruff>=0.5",
    "mypy>=1.10",
    "bandit>=1.7",
    "httpx>=0.27",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "src"
files = ["src", "tests"]

[[tool.mypy.overrides]]
module = "streamlit.*"
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.bandit]
exclude_dirs = ["tests", ".venv"]
```

- [ ] **Step 2: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
.env
*.egg-info/
```

- [ ] **Step 3: Create `.env.example`**

```
PRICING_COPILOT_MODEL_NAME=gpt-4.1-mini
PRICING_COPILOT_REQUEST_TIMEOUT_SECONDS=30
PRICING_COPILOT_MAX_AGENT_TURNS=6
PRICING_COPILOT_POLICY__MAX_PRICE_MOVEMENT_PCT=5.0
```

- [ ] **Step 4: Create empty package/test init files**

`src/pricing_copilot/__init__.py`:
```python
"""Pricing Decision Copilot - governed pricing decision-support prototype."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 5: Resolve dependencies**

Run: `uv sync --all-groups`
Expected: creates `.venv/` and `uv.lock`, exits 0.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example uv.lock src/pricing_copilot/__init__.py tests/__init__.py
git commit -m "chore: scaffold uv project and tooling config"
```

---

## Task 2: Typed contracts

**Files:**
- Create: `src/pricing_copilot/contracts.py`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Consumes: nothing (base module).
- Produces: all model/enum names listed in the interfaces summary above.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contracts.py
from datetime import date

import pytest
from pydantic import ValidationError

from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    PriceRange,
    Product,
    Recommendation,
    RecommendationAction,
    Region,
    Segment,
)


def test_analysis_period_rejects_end_before_start():
    with pytest.raises(ValidationError):
        AnalysisPeriod(start_month=date(2026, 3, 1), end_month=date(2026, 1, 1))


def test_portfolio_question_round_trips():
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(
            start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)
        ),
        scenario=None,
    )
    assert question.model_dump()["product"] == "personal_motor"


def test_price_range_rejects_upper_below_lower():
    with pytest.raises(ValidationError):
        PriceRange(lower_pct=3.0, upper_pct=1.0)


def test_recommendation_requires_evidence_domain_enum():
    rec = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        price_range=None,
        rationale="No evidence connected yet.",
        cited_evidence_ids=[],
        confidence=None,
    )
    assert rec.action is RecommendationAction.INVESTIGATE
    assert EvidenceDomain.CLAIMS.value == "claims"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.contracts'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/contracts.py
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Product(str, Enum):
    PERSONAL_MOTOR = "personal_motor"


class Region(str, Enum):
    NORTH_WEST = "north_west"
    SOUTH_EAST = "south_east"


class Segment(str, Enum):
    RENEWAL = "renewal"
    NEW_BUSINESS = "new_business"


class ScenarioName(str, Enum):
    CONTROLLED_INCREASE = "controlled_increase"
    RETENTION_CONCERN = "retention_concern"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class EvidenceDomain(str, Enum):
    CLAIMS = "claims"
    CONVERSION = "conversion"
    MARKET_INTELLIGENCE = "market_intelligence"
    PRICING_HISTORY = "pricing_history"


class RecommendationAction(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    HOLD = "hold"
    INVESTIGATE = "investigate"


class AnalystDecisionType(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    REJECT = "reject"
    REQUEST_INVESTIGATION = "request_investigation"


class AnalysisPeriod(BaseModel):
    start_month: date
    end_month: date

    @model_validator(mode="after")
    def check_ordering(self) -> "AnalysisPeriod":
        if self.end_month < self.start_month:
            raise ValueError("end_month must not be before start_month")
        return self


class PortfolioQuestion(BaseModel):
    product: Product
    region: Region
    segment: Segment
    analysis_period: AnalysisPeriod
    scenario: ScenarioName | None = None


class MissingEvidence(BaseModel):
    domain: EvidenceDomain
    reason: str


class SpecialistReport(BaseModel):
    domain: EvidenceDomain
    status: str = Field(pattern="^(completed|missing_evidence|error)$")
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class PriceRange(BaseModel):
    lower_pct: float
    upper_pct: float

    @model_validator(mode="after")
    def check_bounds(self) -> "PriceRange":
        if self.upper_pct < self.lower_pct:
            raise ValueError("upper_pct must not be below lower_pct")
        return self


class Recommendation(BaseModel):
    action: RecommendationAction
    price_range: PriceRange | None = None
    rationale: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class GovernanceOutcome(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)


class AnalystDecision(BaseModel):
    decision: AnalystDecisionType
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    decided_at: datetime


class WorkflowResult(BaseModel):
    question: PortfolioQuestion
    specialist_reports: list[SpecialistReport]
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    missing_evidence: list[MissingEvidence]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_contracts.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/contracts.py tests/test_contracts.py
git commit -m "feat: add typed contracts for portfolio workflow"
```

---

## Task 3: Portfolio catalog validation

**Files:**
- Create: `src/pricing_copilot/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `Product`, `Region`, `Segment` from `contracts.py`.
- Produces: `UnsupportedPortfolioError`, `validate_portfolio_combination(product, region, segment) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog.py
import pytest

from pricing_copilot.catalog import UnsupportedPortfolioError, validate_portfolio_combination
from pricing_copilot.contracts import Product, Region, Segment


def test_supported_combination_does_not_raise():
    validate_portfolio_combination(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)


def test_unsupported_region_raises_with_clear_message():
    with pytest.raises(UnsupportedPortfolioError) as exc_info:
        validate_portfolio_combination(Product.PERSONAL_MOTOR, Region.SOUTH_EAST, Segment.RENEWAL)
    message = str(exc_info.value)
    assert "south_east" in message
    assert "north_west" in message  # names the supported alternative
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.catalog'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/catalog.py
from __future__ import annotations

from pricing_copilot.contracts import Product, Region, Segment

SUPPORTED_PORTFOLIOS: frozenset[tuple[Product, Region, Segment]] = frozenset(
    {
        (Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL),
    }
)


class UnsupportedPortfolioError(ValueError):
    def __init__(self, product: Product, region: Region, segment: Segment) -> None:
        supported = ", ".join(
            f"{p.value}/{r.value}/{s.value}" for (p, r, s) in sorted(SUPPORTED_PORTFOLIOS)
        )
        message = (
            f"Unsupported portfolio combination: product={product.value}, "
            f"region={region.value}, segment={segment.value}. "
            f"This prototype currently supports: {supported}."
        )
        super().__init__(message)
        self.product = product
        self.region = region
        self.segment = segment


def validate_portfolio_combination(product: Product, region: Region, segment: Segment) -> None:
    if (product, region, segment) not in SUPPORTED_PORTFOLIOS:
        raise UnsupportedPortfolioError(product, region, segment)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/catalog.py tests/test_catalog.py
git commit -m "feat: add supported-portfolio catalog validation"
```

---

## Task 4: Settings / configuration

**Files:**
- Create: `src/pricing_copilot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PolicySettings` (with `max_price_movement_pct: float`), `Settings` (with `model_name: str`, `request_timeout_seconds: float`, `max_agent_turns: int`, `policy: PolicySettings`), `get_settings() -> Settings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os

from pricing_copilot.config import Settings, get_settings


def test_settings_have_sane_defaults():
    settings = Settings()
    assert settings.model_name
    assert settings.policy.max_price_movement_pct == 5.0


def test_settings_read_model_name_from_env(monkeypatch):
    monkeypatch.setenv("PRICING_COPILOT_MODEL_NAME", "test-model")
    get_settings.cache_clear()
    try:
        assert get_settings().model_name == "test-model"
    finally:
        get_settings.cache_clear()
        os.environ.pop("PRICING_COPILOT_MODEL_NAME", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.config'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/config.py
from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PolicySettings(BaseModel):
    max_price_movement_pct: float = 5.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRICING_COPILOT_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    model_name: str = "gpt-4.1-mini"
    request_timeout_seconds: float = 30.0
    max_agent_turns: int = 6
    policy: PolicySettings = PolicySettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/config.py tests/test_config.py
git commit -m "feat: add configurable settings for model and policy limits"
```

---

## Task 5: Core workflow service (the safe-abstention seam)

**Files:**
- Create: `src/pricing_copilot/workflow.py`
- Test: `tests/test_workflow.py` (this is the primary end-to-end seam test)

**Interfaces:**
- Consumes: `PortfolioQuestion`, `WorkflowResult`, `SpecialistReport`, `MissingEvidence`, `Recommendation`, `RecommendationAction`, `GovernanceOutcome`, `EvidenceDomain` from `contracts.py`; `validate_portfolio_combination`, `UnsupportedPortfolioError` from `catalog.py`; `Settings`, `get_settings` from `config.py`.
- Produces: `run_portfolio_workflow(question: PortfolioQuestion, settings: Settings | None = None) -> WorkflowResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow.py
from datetime import date

import pytest

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    EvidenceDomain,
    PortfolioQuestion,
    Product,
    RecommendationAction,
    Region,
    Segment,
)
from pricing_copilot.workflow import run_portfolio_workflow


def _question(region: Region = Region.NORTH_WEST) -> PortfolioQuestion:
    return PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=region,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(
            start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)
        ),
        scenario=None,
    )


def test_supported_question_returns_investigate_with_missing_evidence():
    result = run_portfolio_workflow(_question())

    assert result.recommendation.action is RecommendationAction.INVESTIGATE
    assert result.recommendation.price_range is None
    assert result.recommendation.cited_evidence_ids == []

    missing_domains = {item.domain for item in result.missing_evidence}
    assert missing_domains == {
        EvidenceDomain.CLAIMS,
        EvidenceDomain.CONVERSION,
        EvidenceDomain.MARKET_INTELLIGENCE,
        EvidenceDomain.PRICING_HISTORY,
    }
    assert all(item.reason for item in result.missing_evidence)

    assert {r.domain for r in result.specialist_reports} == missing_domains
    assert all(r.status == "missing_evidence" for r in result.specialist_reports)

    assert result.governance_outcome.approved is True


def test_unsupported_question_is_rejected_with_clear_message():
    with pytest.raises(UnsupportedPortfolioError) as exc_info:
        run_portfolio_workflow(_question(region=Region.SOUTH_EAST))
    assert "south_east" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.workflow'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/workflow.py
from __future__ import annotations

from pricing_copilot.catalog import validate_portfolio_combination
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    EvidenceDomain,
    GovernanceOutcome,
    MissingEvidence,
    PortfolioQuestion,
    Recommendation,
    RecommendationAction,
    SpecialistReport,
    WorkflowResult,
)

REQUIRED_EVIDENCE_DOMAINS: tuple[EvidenceDomain, ...] = (
    EvidenceDomain.CLAIMS,
    EvidenceDomain.CONVERSION,
    EvidenceDomain.MARKET_INTELLIGENCE,
    EvidenceDomain.PRICING_HISTORY,
)


def _missing_evidence_reason(domain: EvidenceDomain) -> str:
    return (
        f"No {domain.value} evidence source is connected in this prototype slice yet, "
        "so no claim in this domain can be supported."
    )


def run_portfolio_workflow(
    question: PortfolioQuestion, settings: Settings | None = None
) -> WorkflowResult:
    validate_portfolio_combination(question.product, question.region, question.segment)
    settings = settings or get_settings()

    missing_evidence = [
        MissingEvidence(domain=domain, reason=_missing_evidence_reason(domain))
        for domain in REQUIRED_EVIDENCE_DOMAINS
    ]
    specialist_reports = [
        SpecialistReport(
            domain=domain,
            status="missing_evidence",
            evidence_ids=[],
            summary=f"{domain.value} specialist has no evidence source connected yet.",
            missing_evidence=[
                MissingEvidence(domain=domain, reason=_missing_evidence_reason(domain))
            ],
        )
        for domain in REQUIRED_EVIDENCE_DOMAINS
    ]
    recommendation = Recommendation(
        action=RecommendationAction.INVESTIGATE,
        price_range=None,
        rationale=(
            "Investigation is required: no evidence sources are connected yet for this "
            "prototype slice, so no pricing claim can be supported."
        ),
        cited_evidence_ids=[],
        confidence=None,
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

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/workflow.py tests/test_workflow.py
git commit -m "feat: add safe-abstention portfolio workflow service boundary"
```

---

## Task 6: FastAPI entry point

**Files:**
- Create: `src/pricing_copilot/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `run_portfolio_workflow` from `workflow.py`; `UnsupportedPortfolioError` from `catalog.py`; `PortfolioQuestion`, `WorkflowResult` from `contracts.py`.
- Produces: `app` (FastAPI instance) with `POST /workflow` and `GET /health`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
from fastapi.testclient import TestClient

from pricing_copilot.api import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workflow_endpoint_returns_investigate_for_supported_portfolio():
    payload = {
        "product": "personal_motor",
        "region": "north_west",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": None,
    }
    response = client.post("/workflow", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["action"] == "investigate"
    assert len(body["missing_evidence"]) == 4


def test_workflow_endpoint_rejects_unsupported_region():
    payload = {
        "product": "personal_motor",
        "region": "south_east",
        "segment": "renewal",
        "analysis_period": {"start_month": "2026-01-01", "end_month": "2026-06-01"},
        "scenario": None,
    }
    response = client.post("/workflow", json=payload)
    assert response.status_code == 422
    assert "south_east" in response.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.api'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/api.py
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import PortfolioQuestion, WorkflowResult
from pricing_copilot.workflow import run_portfolio_workflow

app = FastAPI(
    title="Pricing Decision Copilot",
    description="Governed decision-support prototype for portfolio pricing questions.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/workflow", response_model=WorkflowResult)
def submit_portfolio_question(question: PortfolioQuestion) -> WorkflowResult:
    try:
        return run_portfolio_workflow(question)
    except UnsupportedPortfolioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/api.py tests/test_api.py
git commit -m "feat: expose portfolio workflow through FastAPI"
```

---

## Task 7: CLI entry point

**Files:**
- Create: `src/pricing_copilot/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_portfolio_workflow` from `workflow.py`; `UnsupportedPortfolioError` from `catalog.py`; `PortfolioQuestion`, `AnalysisPeriod`, `Product`, `Region`, `Segment`, `ScenarioName` from `contracts.py`.
- Produces: `main(argv: list[str] | None = None) -> int`, registered as the `pricing-copilot` console script.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json

from pricing_copilot.cli import main


def test_cli_prints_investigate_result_for_supported_portfolio(capsys):
    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "north_west",
            "--segment",
            "renewal",
            "--start-month",
            "2026-01-01",
            "--end-month",
            "2026-06-01",
        ]
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["recommendation"]["action"] == "investigate"


def test_cli_reports_clear_error_for_unsupported_region(capsys):
    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "south_east",
            "--segment",
            "renewal",
            "--start-month",
            "2026-01-01",
            "--end-month",
            "2026-06-01",
        ]
    )
    assert exit_code == 1
    assert "south_east" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_copilot.cli'`

- [ ] **Step 3: Write the implementation**

```python
# src/pricing_copilot/cli.py
from __future__ import annotations

import argparse
import sys
from datetime import date

from pydantic import ValidationError

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.workflow import run_portfolio_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricing-copilot",
        description="Submit a portfolio pricing question to the governed workflow.",
    )
    parser.add_argument("--product", required=True, choices=[p.value for p in Product])
    parser.add_argument("--region", required=True, choices=[r.value for r in Region])
    parser.add_argument("--segment", required=True, choices=[s.value for s in Segment])
    parser.add_argument("--start-month", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-month", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--scenario", required=False, choices=[s.value for s in ScenarioName], default=None
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        question = PortfolioQuestion(
            product=Product(args.product),
            region=Region(args.region),
            segment=Segment(args.segment),
            analysis_period=AnalysisPeriod(
                start_month=date.fromisoformat(args.start_month),
                end_month=date.fromisoformat(args.end_month),
            ),
            scenario=ScenarioName(args.scenario) if args.scenario else None,
        )
    except ValidationError as exc:
        print(f"Invalid portfolio question: {exc}", file=sys.stderr)
        return 1

    try:
        result = run_portfolio_workflow(question)
    except UnsupportedPortfolioError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pricing_copilot/cli.py tests/test_cli.py
git commit -m "feat: add CLI entry point for the portfolio workflow"
```

---

## Task 8: Streamlit entry point

**Files:**
- Create: `src/pricing_copilot/streamlit_app.py`

**Interfaces:**
- Consumes: `run_portfolio_workflow` from `workflow.py`; `UnsupportedPortfolioError` from `catalog.py`; contracts from `contracts.py`.
- Produces: a Streamlit page runnable via `streamlit run src/pricing_copilot/streamlit_app.py`.

No automated test for this task (Streamlit apps are exercised manually per the ticket's scope — the workflow logic itself is already covered by Task 5's tests). Verification is a manual run in Step 2.

- [ ] **Step 1: Write the implementation**

```python
# src/pricing_copilot/streamlit_app.py
from __future__ import annotations

from datetime import date

import streamlit as st

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.workflow import run_portfolio_workflow

st.set_page_config(page_title="Pricing Decision Copilot", layout="wide")
st.title("Pricing Decision Copilot")
st.caption(
    "Governed decision-support prototype. This build has no evidence sources connected, "
    "so every supported question safely returns an investigate outcome."
)

with st.form("portfolio_question"):
    col1, col2, col3 = st.columns(3)
    product = col1.selectbox("Product", options=list(Product), format_func=lambda p: p.value)
    region = col2.selectbox("Region", options=list(Region), format_func=lambda r: r.value)
    segment = col3.selectbox("Segment", options=list(Segment), format_func=lambda s: s.value)

    col4, col5 = st.columns(2)
    start_month = col4.date_input("Analysis start month", value=date(2026, 1, 1))
    end_month = col5.date_input("Analysis end month", value=date(2026, 6, 1))

    scenario_choice = st.selectbox(
        "Scenario (optional)",
        options=[None, *list(ScenarioName)],
        format_func=lambda s: "None" if s is None else s.value,
    )

    submitted = st.form_submit_button("Run analysis")

if submitted:
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
    else:
        st.subheader(f"Recommendation: {result.recommendation.action.value}")
        st.write(result.recommendation.rationale)

        st.subheader("Missing evidence")
        for item in result.missing_evidence:
            st.warning(f"**{item.domain.value}**: {item.reason}")

        st.subheader("Specialist reports")
        for report in result.specialist_reports:
            st.write(f"- **{report.domain.value}** ({report.status}): {report.summary}")

        st.subheader("Governance outcome")
        st.json(result.governance_outcome.model_dump())
```

- [ ] **Step 2: Manually verify it runs**

Run: `uv run streamlit run src/pricing_copilot/streamlit_app.py --server.headless true &` then `curl -sf http://localhost:8501 > /dev/null && echo OK`
Expected: `OK`, then stop the background server (`kill %1`).

- [ ] **Step 3: Commit**

```bash
git add src/pricing_copilot/streamlit_app.py
git commit -m "feat: add Streamlit entry point for the portfolio workflow"
```

---

## Task 9: Quality command and secret scan

**Files:**
- Create: `scripts/quality.sh`
- Create: `scripts/check_secrets.py`
- Test: `tests/test_check_secrets.py`

**Interfaces:**
- Consumes: nothing (standalone script using stdlib only, so it has no import-time dependency on `pricing_copilot`).
- Produces: `find_secret_matches(paths: list[str]) -> list[str]` (importable for the test) and a `scripts/check_secrets.py` CLI that exits 1 if any match is found.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_check_secrets.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_secrets import find_secret_matches  # noqa: E402


def test_flags_an_aws_style_key(tmp_path):
    suspect = tmp_path / "config.py"
    suspect.write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    matches = find_secret_matches([str(suspect)])
    assert matches


def test_clean_file_has_no_matches(tmp_path):
    clean = tmp_path / "clean.py"
    clean.write_text('greeting = "hello world"\n')
    matches = find_secret_matches([str(clean)])
    assert matches == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_check_secrets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'check_secrets'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/check_secrets.py
"""Lightweight secret-scanning check with no third-party dependency."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "generic_api_key_assignment": re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9/+_-]{16,}['\"]"
    ),
    "private_key_block": re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
}

EXCLUDED_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".ico", ".svg"}


def find_secret_matches(paths: list[str]) -> list[str]:
    matches: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix in EXCLUDED_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{path}:{lineno}: possible {name}")
    return matches


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    matches = find_secret_matches(_tracked_files())
    if matches:
        print("Potential secrets found:", file=sys.stderr)
        for match in matches:
            print(f"  {match}", file=sys.stderr)
        return 1
    print("No potential secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_check_secrets.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Create the quality command**

```bash
# scripts/quality.sh
#!/usr/bin/env bash
set -euo pipefail

echo "==> Ruff"
uv run ruff check .

echo "==> MyPy"
uv run mypy

echo "==> Pytest"
uv run pytest

echo "==> Bandit"
uv run bandit -q -r src

echo "==> Secret scan"
uv run python scripts/check_secrets.py

echo "All quality checks passed."
```

Run: `chmod +x scripts/quality.sh`

- [ ] **Step 6: Commit**

```bash
git add scripts/quality.sh scripts/check_secrets.py tests/test_check_secrets.py
git commit -m "chore: add single quality command and secret-scanning check"
```

---

## Task 10: README setup instructions

**Files:**
- Modify: `README.md` (append a new `## Setup and running the prototype` section before `## Delivery roadmap`)

- [ ] **Step 1: Insert setup section**

Insert this section into `README.md` immediately before the `## Delivery roadmap` heading:

```markdown
## Setup and running the prototype

This build implements [Issue #2](https://github.com/talibilat/pricing-analyst-copilot/issues/2): a runnable vertical slice that safely abstains because no evidence sources are connected yet.

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

### Install

```bash
uv sync --all-groups
cp .env.example .env
```

### Run the API

```bash
uv run uvicorn pricing_copilot.api:app --reload
```

Then submit a supported portfolio question:

```bash
curl -s -X POST http://127.0.0.1:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{"product":"personal_motor","region":"north_west","segment":"renewal","analysis_period":{"start_month":"2026-01-01","end_month":"2026-06-01"},"scenario":null}'
```

### Run the CLI

```bash
uv run pricing-copilot \
  --product personal_motor --region north_west --segment renewal \
  --start-month 2026-01-01 --end-month 2026-06-01
```

### Run the Streamlit interface

```bash
uv run streamlit run src/pricing_copilot/streamlit_app.py
```

### Run the quality command

```bash
./scripts/quality.sh
```

This runs Ruff, MyPy, Pytest, Bandit, and the secret-scanning check.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add setup and run instructions for the vertical slice"
```

---

## Task 11: Full verification pass

- [ ] **Step 1: Run the full quality command**

Run: `./scripts/quality.sh`
Expected: every section prints its check name, ends with `All quality checks passed.`, exit code 0. Fix any Ruff/MyPy/Bandit findings by editing the affected file directly (do not disable rules) and re-run until clean.

- [ ] **Step 2: Run the full test suite once more standalone**

Run: `uv run pytest -v`
Expected: all tests pass, including the primary end-to-end seam tests in `tests/test_workflow.py` and `tests/test_api.py`.

- [ ] **Step 3: Manual smoke test of all three entry points**

Run the API, CLI, and Streamlit commands from the README and confirm each returns/renders an `investigate` outcome with four missing-evidence reasons for the supported portfolio, and a clear rejection message for `south_east`.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve quality command findings"
```

(Skip this commit if Step 1 already passed clean on the first run.)
