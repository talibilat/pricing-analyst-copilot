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

# Maximum number of rows a validated free-form SQL query may return to the caller.
FREEFORM_ROW_LIMIT: Final = 200

# Column name that carries scenario partitioning. It is never queryable by callers:
# scenario scoping is applied by the query layer via shadowing temp views, so this
# column must never appear in a free-form SELECT.
_SCENARIO_COLUMN: Final = "scenario"

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


@dataclass(frozen=True)
class FreeformSqlRequest:
    """A raw free-form SQL string plus the scenario it must be scoped to.

    The ``sql`` is untrusted model/user text. It is validated against the parsed
    AST before execution; ``scenario`` comes from the closed ``ScenarioName`` enum
    and is applied by the query layer, never trusted from the SQL text itself.
    """

    sql: str
    scenario: ScenarioName


@dataclass(frozen=True)
class FreeformSqlResult:
    """The capped, scenario-scoped result of a validated free-form SELECT."""

    sql: str
    columns: tuple[str, ...]
    rows: list[tuple[object, ...]]
    scenario: ScenarioName
    database_version: str


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


def _iter_ast_nodes(obj: object) -> Iterable[dict[str, Any]]:
    """Yield every dict node in a parsed json_serialize_sql tree, depth-first."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_ast_nodes(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_ast_nodes(value)


def _serialize_sql_ast(sql: str) -> dict[str, Any]:
    """Return DuckDB's parsed AST for ``sql`` using its built-in serializer.

    This uses the same parser that would execute the query, so there is no
    dialect-mismatch risk. Runs on a throwaway in-memory connection - it never
    touches the analytics artifact and executes nothing from ``sql``.
    """
    connection = duckdb.connect()
    try:
        serialized = connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()
    finally:
        connection.close()
    if serialized is None or serialized[0] is None:
        raise ValueError("Free-form SQL rejected: the statement could not be parsed.")
    parsed = json.loads(serialized[0])
    if not isinstance(parsed, dict):
        raise ValueError("Free-form SQL rejected: the statement could not be parsed.")
    return parsed


def validate_freeform_sql(sql: str) -> frozenset[str]:
    """Validate ``sql`` as a single read-only SELECT over allowlisted tables.

    Raises ``ValueError`` naming the first violation found. Nothing is executed:
    validation is a pure inspection of the parsed AST. Returns the set of base
    tables the query references (all guaranteed to be in ``SOURCE_TABLES``).

    Controls enforced (default-deny):
    - the text must parse as exactly one statement whose root is ``SELECT_NODE``
      (blocks mutations, DDL, PRAGMA/ATTACH/COPY/EXPORT/SET/LOAD and stacked
      statements, which the serializer either rejects outright or returns as
      more than one statement);
    - every ``BASE_TABLE`` must be unqualified (empty schema and catalog) and
      name one of the four allowlisted tables, unless it names a CTE defined in
      the query;
    - ``TABLE_FUNCTION`` sources (read_csv/read_parquet/generate_series/...) are
      rejected outright;
    - the ``scenario`` column is never selectable, and every other column
      reference must resolve to an allowlisted field or an alias/CTE the query
      itself introduces.
    """
    parsed = _serialize_sql_ast(sql)
    if parsed.get("error"):
        detail = parsed.get("error_message", "only read-only SELECT statements are permitted")
        raise ValueError(f"Free-form SQL rejected: {detail}")

    statements = parsed.get("statements")
    if not isinstance(statements, list) or len(statements) != 1:
        found = len(statements) if isinstance(statements, list) else 0
        raise ValueError(
            "Free-form SQL rejected: exactly one SELECT statement is permitted, "
            f"found {found}."
        )

    root = statements[0].get("node", {}) if isinstance(statements[0], dict) else {}
    if not isinstance(root, dict) or root.get("type") != "SELECT_NODE":
        node_type = root.get("type") if isinstance(root, dict) else None
        raise ValueError(
            f"Free-form SQL rejected: only SELECT statements are permitted, found {node_type!r}."
        )

    nodes = list(_iter_ast_nodes(parsed))

    cte_names: set[str] = set()
    known_aliases: set[str] = set()
    for node in nodes:
        cte_map = node.get("cte_map")
        if isinstance(cte_map, dict):
            for entry in cte_map.get("map", []):
                key = entry.get("key") if isinstance(entry, dict) else None
                if isinstance(key, str) and key:
                    cte_names.add(key)
        alias = node.get("alias")
        if isinstance(alias, str) and alias:
            known_aliases.add(alias)

    referenced_tables: set[str] = set()
    for node in nodes:
        node_type = node.get("type")
        if node_type == "TABLE_FUNCTION":
            raise ValueError(
                "Free-form SQL rejected: table functions and external file access "
                "(e.g. read_csv, read_parquet, generate_series) are not permitted."
            )
        if node_type != "BASE_TABLE":
            continue
        table_name = node.get("table_name", "") or ""
        schema_name = node.get("schema_name", "") or ""
        catalog_name = node.get("catalog_name", "") or ""
        if schema_name or catalog_name:
            qualifier = ".".join(part for part in (catalog_name, schema_name) if part)
            raise ValueError(
                "Free-form SQL rejected: schema- or catalog-qualified access is not "
                f"permitted ({qualifier}.{table_name})."
            )
        if table_name in cte_names:
            continue
        if table_name not in SOURCE_TABLES:
            raise ValueError(
                f"Free-form SQL rejected: table {table_name!r} is not in the allowlist."
            )
        referenced_tables.add(table_name)

    allowed_columns = {column for table in referenced_tables for column in SOURCE_TABLES[table]}
    valid_identifiers = allowed_columns | known_aliases | cte_names
    for node in nodes:
        if node.get("class") != "COLUMN_REF":
            continue
        column_names = node.get("column_names") or []
        if not column_names:
            continue
        last_segment = column_names[-1]
        if last_segment == _SCENARIO_COLUMN:
            raise ValueError(
                "Free-form SQL rejected: the scenario column is not selectable; "
                "scenario scoping is applied automatically."
            )
        if last_segment not in valid_identifiers:
            raise ValueError(
                f"Free-form SQL rejected: column {last_segment!r} is not an allowlisted field."
            )

    return frozenset(referenced_tables)


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

    def run_freeform_sql(self, request: FreeformSqlRequest) -> FreeformSqlResult:
        """Validate and execute a free-form SELECT, scoped to ``request.scenario``.

        The SQL is validated against its parsed AST first (see
        ``validate_freeform_sql``); nothing runs until validation passes. Scenario
        scoping is enforced by the query layer - not by trusting any WHERE clause
        the caller wrote - by creating scenario-scoped temp views that shadow the
        four base tables on the read-only connection before the validated SQL
        runs. The result is capped to ``FREEFORM_ROW_LIMIT`` rows.
        """
        validate_freeform_sql(request.sql)
        self.ensure()
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            catalog_row = connection.execute("SELECT current_catalog()").fetchone()
            if catalog_row is None:
                raise ValueError("Free-form SQL rejected: analytics catalogue is unavailable.")
            catalog = catalog_row[0]
            for table, table_columns in SOURCE_TABLES.items():
                # Every reference is from the fixed allowlist; scenario.value comes
                # from the closed ScenarioName enum (never caller text) and DDL cannot
                # be parameterized, so it is inlined. The source is qualified with the
                # live catalog name to avoid recursive self-reference by the shadowing
                # temp view. The projection omits the scenario column entirely.
                projection = ", ".join(table_columns)
                connection.execute(
                    f"CREATE TEMP VIEW {table} AS SELECT {projection} "  # nosec B608
                    f'FROM "{catalog}".main.{table} '
                    f"WHERE {_SCENARIO_COLUMN} = '{request.scenario.value}'"
                )
            # Push the row cap into the SQL DuckDB actually executes, wrapping the
            # validated query as a subquery under an outer LIMIT. DuckDB applies
            # LIMIT pushdown at plan time, so an enormous intermediate result (for
            # example an implicit cross join over the allowlisted table) is never
            # fully materialized. request.sql is a single validated SELECT with no
            # trailing semicolon (see validate_freeform_sql), so it composes as a
            # subquery; a caller's own inner LIMIT still wins over this outer cap.
            cursor = connection.execute(
                f"SELECT * FROM ({request.sql}) AS _freeform_result "  # nosec B608
                f"LIMIT {FREEFORM_ROW_LIMIT}"
            )
            columns = tuple(descriptor[0] for descriptor in cursor.description)
            rows = cursor.fetchall()
        finally:
            connection.close()
        return FreeformSqlResult(
            sql=request.sql,
            columns=columns,
            rows=rows[:FREEFORM_ROW_LIMIT],
            scenario=request.scenario,
            database_version=ANALYTICS_DATABASE_VERSION,
        )

    def execute_freeform_sql(self, sql: str, scenario: ScenarioName) -> FreeformSqlResult:
        """Convenience wrapper: validate and run ``sql`` scoped to ``scenario``."""
        return self.run_freeform_sql(FreeformSqlRequest(sql=sql, scenario=scenario))

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
