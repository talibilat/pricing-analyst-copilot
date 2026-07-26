from pathlib import Path

import duckdb
import pytest

from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.persistent import (
    ANALYTICS_DATABASE_VERSION,
    FREEFORM_ROW_LIMIT,
    SOURCE_TABLES,
    FreeformSqlRequest,
    PersistentAnalyticsDatabase,
    build_analytics_database,
)


@pytest.fixture()
def database(tmp_path: Path) -> PersistentAnalyticsDatabase:
    path = build_analytics_database(tmp_path / "synthetic.duckdb")
    return PersistentAnalyticsDatabase(path)


def _row_count(path: Path, table: str, scenario: ScenarioName) -> int:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        result = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE scenario = ?",  # noqa: S608 - fixed allowlist name
            [scenario.value],
        ).fetchone()
    finally:
        connection.close()
    assert result is not None
    return int(result[0])


def test_build_creates_versioned_scenario_isolated_database(tmp_path: Path) -> None:
    path = build_analytics_database(tmp_path / "synthetic.duckdb")
    database = PersistentAnalyticsDatabase(path)

    for scenario in ScenarioName:
        for source in SOURCE_TABLES:
            result = database.query_source(source, scenario)
            assert result.rows

    connection = duckdb.connect(str(path), read_only=True)
    try:
        versions = connection.execute(
            "SELECT scenario, database_version, checksum FROM dataset_versions ORDER BY scenario"
        ).fetchall()
        catalogue_rows = connection.execute("SELECT COUNT(*) FROM schema_catalogue").fetchone()
    finally:
        connection.close()
    assert {scenario for scenario, _, _ in versions} == {
        scenario.value for scenario in ScenarioName
    }
    assert all(
        version == ANALYTICS_DATABASE_VERSION and checksum for _, version, checksum in versions
    )
    assert catalogue_rows is not None
    assert catalogue_rows[0] == sum(len(columns) for columns in SOURCE_TABLES.values())


def test_catalogue_documents_types_units_and_portfolio_restrictions(tmp_path: Path) -> None:
    database = PersistentAnalyticsDatabase(tmp_path / "synthetic.duckdb")
    catalogue = database.schema_catalogue()

    assert catalogue["permitted_joins"] == []
    assert catalogue["scenario_metadata"] == "dataset_versions"
    assert "customer-level" in str(catalogue["portfolio_restrictions"])
    claims = next(table for table in catalogue["tables"] if table["name"] == "claims")
    assert claims["source_version"]
    assert any(column["unit"] == "GBP" for column in claims["columns"])


def test_unknown_source_is_rejected_without_arbitrary_sql(tmp_path: Path) -> None:
    database = PersistentAnalyticsDatabase(tmp_path / "synthetic.duckdb")
    with pytest.raises(ValueError, match="not available"):
        database.query_source("claims; DROP TABLE claims", ScenarioName.CONTROLLED_INCREASE)


def test_query_plan_allows_only_permitted_columns(tmp_path: Path) -> None:
    database = PersistentAnalyticsDatabase(tmp_path / "synthetic.duckdb")
    plan = database.plan_query(
        "claims",
        ScenarioName.CONTROLLED_INCREASE,
        columns=("period", "incurred_loss_gbp"),
    )

    result = database.execute_plan(plan)

    assert result.columns == ("period", "incurred_loss_gbp")
    with pytest.raises(ValueError, match="not permitted"):
        database.plan_query(
            "claims", ScenarioName.CONTROLLED_INCREASE, columns=("customer_id",)
        )


# --------------------------------------------------------------------------- #
# Free-form validated SQL: allowed shapes must execute and return real rows.   #
# --------------------------------------------------------------------------- #


def test_freeform_allows_projection_and_filter(database: PersistentAnalyticsDatabase) -> None:
    result = database.execute_freeform_sql(
        "SELECT period, incurred_loss_gbp FROM claims WHERE region = 'north_west'",
        ScenarioName.CONTROLLED_INCREASE,
    )
    assert result.columns == ("period", "incurred_loss_gbp")
    assert result.rows
    assert result.scenario is ScenarioName.CONTROLLED_INCREASE
    assert result.database_version == ANALYTICS_DATABASE_VERSION
    assert result.sql.startswith("SELECT period, incurred_loss_gbp")


def test_freeform_run_request_object_returns_full_metadata(
    database: PersistentAnalyticsDatabase,
) -> None:
    request = FreeformSqlRequest(
        sql="SELECT period, sales FROM conversion ORDER BY period",
        scenario=ScenarioName.DRIFT_MONITORING,
    )
    result = database.run_freeform_sql(request)
    assert result.sql == request.sql
    assert result.columns == ("period", "sales")
    assert result.scenario is ScenarioName.DRIFT_MONITORING
    assert result.database_version == ANALYTICS_DATABASE_VERSION
    assert result.rows


def test_freeform_allows_aggregate_alias_and_ordering(
    database: PersistentAnalyticsDatabase,
) -> None:
    result = database.execute_freeform_sql(
        "SELECT region, SUM(incurred_loss_gbp) AS total_loss "
        "FROM claims GROUP BY region ORDER BY total_loss DESC",
        ScenarioName.CONTROLLED_INCREASE,
    )
    assert result.columns == ("region", "total_loss")
    assert result.rows
    losses = [row[1] for row in result.rows]
    assert losses == sorted(losses, reverse=True)


def test_freeform_allows_common_table_expression(
    database: PersistentAnalyticsDatabase,
) -> None:
    result = database.execute_freeform_sql(
        "WITH monthly AS (SELECT period, sales FROM conversion) "
        "SELECT period, sales FROM monthly ORDER BY period",
        ScenarioName.RETENTION_CONCERN,
    )
    assert result.columns == ("period", "sales")
    assert result.rows


def test_freeform_allows_join_across_two_allowlisted_tables(
    database: PersistentAnalyticsDatabase,
) -> None:
    result = database.execute_freeform_sql(
        "SELECT c.period, c.incurred_loss_gbp, v.quotes "
        "FROM claims AS c "
        "JOIN conversion AS v "
        "ON c.period = v.period AND c.product = v.product "
        "AND c.region = v.region AND c.segment = v.segment "
        "ORDER BY c.period",
        ScenarioName.CONTROLLED_INCREASE,
    )
    assert result.columns == ("period", "incurred_loss_gbp", "quotes")
    assert result.rows


# --------------------------------------------------------------------------- #
# Free-form validated SQL: rejected shapes must never execute.                 #
# A ValueError must fire and no rows are ever produced.                        #
# --------------------------------------------------------------------------- #


def _assert_rejected_without_execution(
    database: PersistentAnalyticsDatabase, sql: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match) as excinfo:
        database.execute_freeform_sql(sql, ScenarioName.CONTROLLED_INCREASE)
    # A rejected statement raises before execution, so no result object and no rows
    # are ever handed back to the caller.
    assert "rows" not in str(excinfo.value)


def test_freeform_rejects_stacked_statements(
    database: PersistentAnalyticsDatabase,
) -> None:
    _assert_rejected_without_execution(
        database,
        "SELECT period FROM claims; DROP TABLE claims",
        "Free-form SQL rejected",
    )


def test_freeform_rejects_stacked_select_statements(
    database: PersistentAnalyticsDatabase,
) -> None:
    _assert_rejected_without_execution(
        database,
        "SELECT period FROM claims; SELECT period FROM conversion",
        "exactly one SELECT statement",
    )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO claims VALUES (1)",
        "UPDATE claims SET claim_count = 0",
        "DELETE FROM claims",
        "CREATE TABLE evil (x INTEGER)",
        "DROP TABLE claims",
        "ALTER TABLE claims ADD COLUMN x INTEGER",
    ],
)
def test_freeform_rejects_mutations(
    database: PersistentAnalyticsDatabase, sql: str
) -> None:
    _assert_rejected_without_execution(database, sql, "Free-form SQL rejected")


def test_freeform_rejects_unknown_table(
    database: PersistentAnalyticsDatabase,
) -> None:
    _assert_rejected_without_execution(
        database,
        "SELECT * FROM customers",
        "not in the allowlist",
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT period FROM main.claims",
        "SELECT period FROM synthetic.main.claims",
    ],
)
def test_freeform_rejects_schema_or_catalog_qualified_access(
    database: PersistentAnalyticsDatabase, sql: str
) -> None:
    _assert_rejected_without_execution(
        database, sql, "schema- or catalog-qualified access is not"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('/tmp/x.parquet')",
        "SELECT * FROM generate_series(1, 10)",
    ],
)
def test_freeform_rejects_table_functions_and_external_files(
    database: PersistentAnalyticsDatabase, sql: str
) -> None:
    _assert_rejected_without_execution(
        database, sql, "table functions and external file access"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA table_info('claims')",
        "ATTACH 'other.db' AS other",
        "COPY claims TO '/tmp/out.csv'",
        "EXPORT DATABASE '/tmp/dump'",
        "SET memory_limit = '1GB'",
        "LOAD spatial",
    ],
)
def test_freeform_rejects_extensions_pragmas_attach_copy_export(
    database: PersistentAnalyticsDatabase, sql: str
) -> None:
    _assert_rejected_without_execution(database, sql, "Free-form SQL rejected")


def test_freeform_rejects_non_catalogue_column(
    database: PersistentAnalyticsDatabase,
) -> None:
    _assert_rejected_without_execution(
        database,
        "SELECT customer_id FROM claims",
        "not an allowlisted field",
    )


def test_freeform_rejects_direct_scenario_column_reference(
    database: PersistentAnalyticsDatabase,
) -> None:
    _assert_rejected_without_execution(
        database,
        "SELECT scenario, period FROM claims",
        "scenario column is not selectable",
    )


def test_freeform_rejects_scenario_bypass_in_where_clause(
    database: PersistentAnalyticsDatabase,
) -> None:
    _assert_rejected_without_execution(
        database,
        "SELECT period FROM claims WHERE scenario = 'retention_concern'",
        "scenario column is not selectable",
    )


def test_freeform_scenario_filter_always_wins(
    database: PersistentAnalyticsDatabase,
) -> None:
    # Even without referencing scenario, results are confined to the requested
    # scenario: the shadowing view applies the filter the caller cannot override.
    controlled = database.execute_freeform_sql(
        "SELECT period, sales FROM conversion ORDER BY period",
        ScenarioName.CONTROLLED_INCREASE,
    )
    retention = database.execute_freeform_sql(
        "SELECT period, sales FROM conversion ORDER BY period",
        ScenarioName.RETENTION_CONCERN,
    )
    expected_controlled = _row_count(
        database.path, "conversion", ScenarioName.CONTROLLED_INCREASE
    )
    assert len(controlled.rows) == expected_controlled
    # Scenarios differ in their synthetic data, so the scoped result sets differ.
    assert controlled.rows != retention.rows


def test_freeform_caps_result_rows_at_two_hundred(
    database: PersistentAnalyticsDatabase,
) -> None:
    # A self cross-join of a 24-row scenario slice produces 576 rows; the cap
    # must trim the returned rows to exactly 200 even though more match.
    result = database.execute_freeform_sql(
        "SELECT c1.period FROM claims AS c1 CROSS JOIN claims AS c2",
        ScenarioName.CONTROLLED_INCREASE,
    )
    assert len(result.rows) == FREEFORM_ROW_LIMIT == 200


def test_freeform_row_cap_holds_with_explicit_limit_and_order(
    database: PersistentAnalyticsDatabase,
) -> None:
    # A caller-supplied LIMIT below the cap is respected as-is.
    result = database.execute_freeform_sql(
        "SELECT period FROM claims ORDER BY period LIMIT 5",
        ScenarioName.CONTROLLED_INCREASE,
    )
    assert len(result.rows) == 5


def test_freeform_rejection_leaves_database_intact(
    database: PersistentAnalyticsDatabase,
) -> None:
    before = _row_count(database.path, "claims", ScenarioName.CONTROLLED_INCREASE)
    with pytest.raises(ValueError):
        database.execute_freeform_sql(
            "SELECT period FROM claims; DROP TABLE claims",
            ScenarioName.CONTROLLED_INCREASE,
        )
    after = _row_count(database.path, "claims", ScenarioName.CONTROLLED_INCREASE)
    assert before == after > 0
