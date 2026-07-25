"""Generate docs/release_manifest.md from the running application's own configuration."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pricing_copilot.config import get_settings
from pricing_copilot.data.persistent import (
    ANALYTICS_DATABASE_VERSION,
    SOURCE_TABLES,
    PersistentAnalyticsDatabase,
)
from pricing_copilot.drift.monitor import DRIFT_REPORT_VERSION
from pricing_copilot.drift.store import load_drift_report
from pricing_copilot.evaluation.golden_set import GOLDEN_SET_VERSION
from pricing_copilot.evaluation.store import load_benchmark_report
from pricing_copilot.versions import current_configuration_versions


def _git_commit() -> str:
    result = subprocess.run(  # nosec B603 B607 - fixed, argument-free local git command
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _row_counts(database_path: Path) -> dict[str, int]:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in SOURCE_TABLES
        }
    finally:
        connection.close()


def main() -> None:
    settings = get_settings()
    versions = current_configuration_versions(settings)
    database = PersistentAnalyticsDatabase(settings.analytics_database_path)
    catalogue = database.schema_catalogue()
    counts = _row_counts(settings.analytics_database_path)
    benchmark = load_benchmark_report(settings)
    drift = load_drift_report(settings)

    lines = [
        "# Release Manifest",
        "",
        f"Generated {datetime.now(UTC).isoformat()} by `scripts/generate_release_manifest.py` "
        "from the running application's own configuration - not hand-typed.",
        "",
        f"- Application commit: `{_git_commit()}`",
        f"- Model: `{versions.model_name}`",
        f"- Recommendation version: `{versions.recommendation_version}`",
        f"- Governance version: `{versions.governance_version}`",
        f"- Prompt version: `{versions.prompt_version}`",
        f"- Agent registry version: `{versions.agent_registry_version}`",
        f"- Tool version: `{versions.tool_version}`",
        f"- Recommendation policy version: `{versions.recommendation_policy_version}`",
        f"- Output schema version: `{versions.output_schema_version}`",
        f"- Scenario dataset version: `{versions.scenario_version}` "
        f"(seed `{versions.scenario_seed}`)",
        f"- Analytics database version: `{ANALYTICS_DATABASE_VERSION}`",
        f"- Max price movement policy: {versions.max_price_movement_pct}%",
        f"- Golden evaluation set version: `{GOLDEN_SET_VERSION}`",
        f"- Drift report version: `{DRIFT_REPORT_VERSION}`",
        "",
        "## Persistent dataset schema catalogue and row counts",
        "",
        "| Table | Permitted columns | Row count | Access | Source version |",
        "|---|---|---|---|---|",
    ]
    for table in catalogue["tables"]:
        name = table["name"]
        lines.append(
            f"| `{name}` | {len(table['columns'])} | {counts.get(name, 'n/a')} "
            f"| {table['access']} | `{table['source_version']}` |"
        )

    if benchmark is not None:
        lines += [
            "",
            "## Latest evaluation report",
            "",
            f"- Report version: `{benchmark.report_version}`",
            f"- Golden set version: `{benchmark.golden_set_version}`",
            f"- Governed cases: {benchmark.governed.actuals.cases_passed} passed, "
            f"{benchmark.governed.actuals.cases_failed} failed, "
            f"{benchmark.governed.actuals.cases_errored} errored",
        ]
    if drift is not None:
        material = len(drift.material_alerts)
        lines += [
            "",
            "## Latest drift report",
            "",
            f"- Report version: `{drift.report_version}`",
            f"- {len(drift.alerts)} total alerts, {material} material",
        ]

    Path("docs/release_manifest.md").write_text("\n".join(lines) + "\n")
    print("Wrote docs/release_manifest.md")


if __name__ == "__main__":
    main()
