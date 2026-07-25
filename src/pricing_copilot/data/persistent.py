"""Versioned, read-only synthetic analytics data for the chat experience."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import duckdb

from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.generation import (
    DEFAULT_SCENARIO_SEED,
    DEFAULT_SCENARIO_VERSION,
    generate_scenario_dataset,
)
from pricing_copilot.data.records import ScenarioDataset

ANALYTICS_DATABASE_VERSION: Final = "synthetic-portfolio-duckdb-v2"

SOURCE_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "claims": (
        "period",
        "product",
        "region",
        "segment",
        "policies_in_force",
        "claim_count",
        "incurred_loss_gbp",
        "earned_premium_gbp",
    ),
    "conversion": (
        "period",
        "product",
        "region",
        "segment",
        "quotes",
        "sales",
        "renewals_due",
        "renewals_retained",
        "average_quoted_premium_gbp",
    ),
    "competitors": (
        "period",
        "region",
        "competitor_name",
        "price_index",
    ),
    "pricing_history": (
        "period",
        "product",
        "region",
        "segment",
        "price_change_pct",
        "rationale",
        "conversion_impact_pct",
        "loss_ratio_impact_pct",
    ),
}

_COLUMN_METADATA: Final[dict[str, dict[str, tuple[str, str]]]] = {
    "claims": {
        "period": ("DATE", "month"),
        "product": ("VARCHAR", "catalogue value"),
        "region": ("VARCHAR", "catalogue value"),
        "segment": ("VARCHAR", "catalogue value"),
        "policies_in_force": ("INTEGER", "policies"),
        "claim_count": ("INTEGER", "claims"),
        "incurred_loss_gbp": ("DOUBLE", "GBP"),
        "earned_premium_gbp": ("DOUBLE", "GBP"),
    },
    "conversion": {
        "period": ("DATE", "month"),
        "product": ("VARCHAR", "catalogue value"),
        "region": ("VARCHAR", "catalogue value"),
        "segment": ("VARCHAR", "catalogue value"),
        "quotes": ("INTEGER", "quotes"),
        "sales": ("INTEGER", "sales"),
        "renewals_due": ("INTEGER", "renewals"),
        "renewals_retained": ("INTEGER", "renewals"),
        "average_quoted_premium_gbp": ("DOUBLE", "GBP"),
    },
    "competitors": {
        "period": ("DATE", "month"),
        "region": ("VARCHAR", "catalogue value"),
        "competitor_name": ("VARCHAR", "synthetic competitor"),
        "price_index": ("DOUBLE", "index points"),
    },
    "pricing_history": {
        "period": ("DATE", "month"),
        "product": ("VARCHAR", "catalogue value"),
        "region": ("VARCHAR", "catalogue value"),
        "segment": ("VARCHAR", "catalogue value"),
        "price_change_pct": ("DOUBLE", "percentage points"),
        "rationale": ("VARCHAR", "text"),
        "conversion_impact_pct": ("DOUBLE", "percentage points"),
        "loss_ratio_impact_pct": ("DOUBLE", "percentage points"),
    },
}


@dataclass(frozen=True)
class QueryResult:
    """A safe tabular result returned by an allowlisted read-only source query."""

    source: str
    columns: tuple[str, ...]
    rows: list[tuple[object, ...]]
    scenario: ScenarioName


@dataclass(frozen=True)
class ReadOnlyQueryPlan:
    """A validated, portfolio-level SELECT plan with no joins or write operations."""

    source: str
    columns: tuple[str, ...]
    scenario: ScenarioName


def _dataset_checksum(dataset: ScenarioDataset) -> str:
    payload = json.dumps(dataset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _create_schema(connection: duckdb.DuckDBPyConnection) -> None:
    for table_name in (*SOURCE_TABLES, "dataset_versions", "schema_catalogue"):
        connection.execute(f"DROP TABLE IF EXISTS {table_name}")

    connection.execute(
        "CREATE TABLE dataset_versions ("
        "scenario VARCHAR PRIMARY KEY, dataset_version VARCHAR NOT NULL, seed BIGINT NOT NULL, "
        "database_version VARCHAR NOT NULL, checksum VARCHAR NOT NULL, "
        "claims_rows INTEGER NOT NULL, "
        "conversion_rows INTEGER NOT NULL, competitors_rows INTEGER NOT NULL, "
        "pricing_history_rows INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE schema_catalogue ("
        "source VARCHAR NOT NULL, field VARCHAR NOT NULL, data_type VARCHAR NOT NULL, "
        "unit VARCHAR NOT NULL, source_version VARCHAR NOT NULL, "
        "access_restriction VARCHAR NOT NULL, PRIMARY KEY (source, field))"
    )
    connection.execute(
        "CREATE TABLE claims (scenario VARCHAR NOT NULL, period DATE NOT NULL, "
        "product VARCHAR NOT NULL, "
        "region VARCHAR NOT NULL, segment VARCHAR NOT NULL, policies_in_force INTEGER NOT NULL, "
        "claim_count INTEGER NOT NULL, incurred_loss_gbp DOUBLE NOT NULL, "
        "earned_premium_gbp DOUBLE NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE conversion (scenario VARCHAR NOT NULL, period DATE NOT NULL, "
        "product VARCHAR NOT NULL, region VARCHAR NOT NULL, segment VARCHAR NOT NULL, "
        "quotes INTEGER NOT NULL, sales INTEGER NOT NULL, "
        "renewals_due INTEGER NOT NULL, renewals_retained INTEGER NOT NULL, "
        "average_quoted_premium_gbp DOUBLE NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE competitors (scenario VARCHAR NOT NULL, period DATE NOT NULL, "
        "region VARCHAR NOT NULL, "
        "competitor_name VARCHAR NOT NULL, price_index DOUBLE NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE pricing_history (scenario VARCHAR NOT NULL, period DATE NOT NULL, "
        "product VARCHAR NOT NULL, region VARCHAR NOT NULL, segment VARCHAR NOT NULL, "
        "price_change_pct DOUBLE NOT NULL, rationale VARCHAR NOT NULL, "
        "conversion_impact_pct DOUBLE NOT NULL, loss_ratio_impact_pct DOUBLE NOT NULL)"
    )


def _insert_dataset(connection: duckdb.DuckDBPyConnection, dataset: ScenarioDataset) -> None:
    scenario = dataset.scenario.value
    connection.executemany(
        "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                scenario,
                row.period,
                row.product.value,
                row.region.value,
                row.segment.value,
                row.policies_in_force,
                row.claim_count,
                row.incurred_loss_gbp,
                row.earned_premium_gbp,
            )
            for row in dataset.claims
        ],
    )
    connection.executemany(
        "INSERT INTO conversion VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                scenario,
                row.period,
                row.product.value,
                row.region.value,
                row.segment.value,
                row.quotes,
                row.sales,
                row.renewals_due,
                row.renewals_retained,
                row.average_quoted_premium_gbp,
            )
            for row in dataset.conversion
        ],
    )
    connection.executemany(
        "INSERT INTO competitors VALUES (?, ?, ?, ?, ?)",
        [
            (scenario, row.period, row.region.value, row.competitor_name, row.price_index)
            for row in dataset.competitors
        ],
    )
    connection.executemany(
        "INSERT INTO pricing_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                scenario,
                row.period,
                row.product.value,
                row.region.value,
                row.segment.value,
                row.price_change_pct,
                row.rationale,
                row.conversion_impact_pct,
                row.loss_ratio_impact_pct,
            )
            for row in dataset.pricing_history
        ],
    )
    connection.execute(
        "INSERT INTO dataset_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            scenario,
            dataset.version,
            dataset.seed,
            ANALYTICS_DATABASE_VERSION,
            _dataset_checksum(dataset),
            len(dataset.claims),
            len(dataset.conversion),
            len(dataset.competitors),
            len(dataset.pricing_history),
        ],
    )


def _insert_schema_catalogue(connection: duckdb.DuckDBPyConnection) -> None:
    rows = [
        (
            source,
            field,
            data_type,
            unit,
            DEFAULT_SCENARIO_VERSION,
            "portfolio_level_read_only",
        )
        for source, fields in _COLUMN_METADATA.items()
        for field, (data_type, unit) in fields.items()
    ]
    connection.executemany("INSERT INTO schema_catalogue VALUES (?, ?, ?, ?, ?, ?)", rows)


def build_analytics_database(
    path: Path,
    *,
    seed: int = DEFAULT_SCENARIO_SEED,
    version: str = DEFAULT_SCENARIO_VERSION,
    scenarios: Iterable[ScenarioName] = ScenarioName,
) -> Path:
    """Build a deterministic DuckDB artifact from every supported synthetic scenario."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        _create_schema(connection)
        _insert_schema_catalogue(connection)
        for scenario in scenarios:
            _insert_dataset(connection, generate_scenario_dataset(scenario, seed, version))
    finally:
        connection.close()
    return path


class PersistentAnalyticsDatabase:
    """Safe reader for the versioned synthetic DuckDB analytical artifact."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def ensure(self) -> Path:
        if not self.path.exists():
            return build_analytics_database(self.path)
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            database_version = connection.execute(
                "SELECT DISTINCT database_version FROM dataset_versions"
            ).fetchall()
            catalogue_count = connection.execute("SELECT COUNT(*) FROM schema_catalogue").fetchone()
        except duckdb.Error:
            return build_analytics_database(self.path)
        finally:
            connection.close()
        if database_version != [(ANALYTICS_DATABASE_VERSION,)] or not catalogue_count:
            return build_analytics_database(self.path)
        if int(catalogue_count[0]) == 0:
            return build_analytics_database(self.path)
        return self.path

    def plan_query(
        self, source: str, scenario: ScenarioName, *, columns: Iterable[str] | None = None
    ) -> ReadOnlyQueryPlan:
        if source not in SOURCE_TABLES:
            raise ValueError(f"Source {source!r} is not available for chat queries.")
        selected_columns = tuple(columns) if columns is not None else SOURCE_TABLES[source]
        if not selected_columns:
            raise ValueError("A read-only query plan must select at least one permitted field.")
        invalid_columns = set(selected_columns) - set(SOURCE_TABLES[source])
        if invalid_columns:
            raise ValueError(
                f"Query plan contains fields not permitted for {source}: {sorted(invalid_columns)}."
            )
        return ReadOnlyQueryPlan(source=source, columns=selected_columns, scenario=scenario)

    def execute_plan(self, plan: ReadOnlyQueryPlan) -> QueryResult:
        if plan.source not in SOURCE_TABLES:
            raise ValueError(f"Source {plan.source!r} is not available for chat queries.")
        invalid_columns = set(plan.columns) - set(SOURCE_TABLES[plan.source])
        if not plan.columns or invalid_columns:
            raise ValueError("Only allowlisted source columns can be queried.")
        self.ensure()
        selected_columns = ", ".join(plan.columns)
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            rows = connection.execute(
                # source and selected_columns only come from the fixed SOURCE_TABLES allowlist.
                f"SELECT {selected_columns} FROM {plan.source} WHERE scenario = ? ORDER BY period",  # nosec B608
                [plan.scenario.value],
            ).fetchall()
        finally:
            connection.close()
        return QueryResult(
            source=plan.source,
            columns=plan.columns,
            rows=rows,
            scenario=plan.scenario,
        )

    def query_source(
        self, source: str, scenario: ScenarioName, *, columns: Iterable[str] | None = None
    ) -> QueryResult:
        return self.execute_plan(self.plan_query(source, scenario, columns=columns))

    def schema_catalogue(self) -> dict[str, Any]:
        self.ensure()
        return {
            "database_version": ANALYTICS_DATABASE_VERSION,
            "tables": [
                {
                    "name": table_name,
                    "columns": [
                        {"name": "scenario", "data_type": "VARCHAR", "unit": "scenario"},
                        *[
                            {
                                "name": field,
                                "data_type": _COLUMN_METADATA[table_name][field][0],
                                "unit": _COLUMN_METADATA[table_name][field][1],
                            }
                            for field in columns
                        ],
                    ],
                    "access": "read_only_portfolio_level",
                    "source_version": DEFAULT_SCENARIO_VERSION,
                }
                for table_name, columns in SOURCE_TABLES.items()
            ],
            "permitted_joins": [],
            "scenario_metadata": "dataset_versions",
            "portfolio_restrictions": "No customer-level, personal, or protected-attribute data.",
        }


if __name__ == "__main__":  # pragma: no cover - manual reproducible build command
    print(build_analytics_database(Path("var/synthetic_portfolio.duckdb")))
