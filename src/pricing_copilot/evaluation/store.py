from __future__ import annotations

from pathlib import Path

from pricing_copilot.config import Settings
from pricing_copilot.evaluation.contracts import BenchmarkReport


def _report_path(settings: Settings) -> Path:
    return Path(settings.evaluation_directory) / "latest.json"


def save_benchmark_report(report: BenchmarkReport, settings: Settings) -> Path:
    path = _report_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    return path


def load_benchmark_report(settings: Settings) -> BenchmarkReport | None:
    path = _report_path(settings)
    if not path.exists():
        return None
    return BenchmarkReport.model_validate_json(path.read_text())
