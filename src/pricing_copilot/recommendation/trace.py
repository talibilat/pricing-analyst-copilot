from __future__ import annotations

from pathlib import Path

from pricing_copilot.contracts import WorkflowResult


def save_baseline_trace(result: WorkflowResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2))


def load_baseline_trace(path: Path) -> WorkflowResult:
    return WorkflowResult.model_validate_json(path.read_text())
