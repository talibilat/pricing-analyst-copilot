from pathlib import Path

import duckdb
import pytest

from pricing_copilot.contracts import ScenarioName
from pricing_copilot.data.persistent import (
    ANALYTICS_DATABASE_VERSION,
    SOURCE_TABLES,
    PersistentAnalyticsDatabase,
    build_analytics_database,
)


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
