from __future__ import annotations

import duckdb

from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.data.generation import (
    DEFAULT_SCENARIO_SEED,
    DEFAULT_SCENARIO_VERSION,
    generate_scenario_dataset,
)
from pricing_copilot.data.records import (
    ClaimsMonthlyRecord,
    CompetitorMonthlyRecord,
    ConversionMonthlyRecord,
    PricingActionRecord,
    ScenarioDataset,
)


class PortfolioDataRepository:
    """Read-only, parameterized access to a generated scenario dataset via DuckDB."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    @classmethod
    def from_dataset(cls, dataset: ScenarioDataset) -> PortfolioDataRepository:
        connection = duckdb.connect(":memory:")
        _load_dataset(connection, dataset)
        return cls(connection)

    @classmethod
    def from_scenario(
        cls,
        scenario: ScenarioName,
        seed: int = DEFAULT_SCENARIO_SEED,
        version: str = DEFAULT_SCENARIO_VERSION,
    ) -> PortfolioDataRepository:
        return cls.from_dataset(generate_scenario_dataset(scenario, seed, version))

    def fetch_claims(
        self, product: Product, region: Region, segment: Segment
    ) -> list[ClaimsMonthlyRecord]:
        rows = self._connection.execute(
            "SELECT period, product, region, segment, policies_in_force, claim_count, "
            "incurred_loss_gbp, earned_premium_gbp FROM claims "
            "WHERE product = ? AND region = ? AND segment = ? ORDER BY period",
            [product.value, region.value, segment.value],
        ).fetchall()
        return [
            ClaimsMonthlyRecord(
                period=row[0],
                product=Product(row[1]),
                region=Region(row[2]),
                segment=Segment(row[3]),
                policies_in_force=row[4],
                claim_count=row[5],
                incurred_loss_gbp=row[6],
                earned_premium_gbp=row[7],
            )
            for row in rows
        ]

    def fetch_conversion(self, product: Product, region: Region) -> list[ConversionMonthlyRecord]:
        rows = self._connection.execute(
            "SELECT period, product, region, segment, quotes, sales, renewals_due, "
            "renewals_retained, average_quoted_premium_gbp FROM conversion "
            "WHERE product = ? AND region = ? ORDER BY segment, period",
            [product.value, region.value],
        ).fetchall()
        return [
            ConversionMonthlyRecord(
                period=row[0],
                product=Product(row[1]),
                region=Region(row[2]),
                segment=Segment(row[3]),
                quotes=row[4],
                sales=row[5],
                renewals_due=row[6],
                renewals_retained=row[7],
                average_quoted_premium_gbp=row[8],
            )
            for row in rows
        ]

    def fetch_competitors(self, region: Region) -> list[CompetitorMonthlyRecord]:
        rows = self._connection.execute(
            "SELECT period, region, competitor_name, price_index FROM competitors "
            "WHERE region = ? ORDER BY competitor_name, period",
            [region.value],
        ).fetchall()
        return [
            CompetitorMonthlyRecord(
                period=row[0], region=Region(row[1]), competitor_name=row[2], price_index=row[3]
            )
            for row in rows
        ]

    def fetch_pricing_history(
        self, product: Product, region: Region, segment: Segment
    ) -> list[PricingActionRecord]:
        rows = self._connection.execute(
            "SELECT period, product, region, segment, price_change_pct, rationale, "
            "conversion_impact_pct, loss_ratio_impact_pct FROM pricing_history "
            "WHERE product = ? AND region = ? AND segment = ? ORDER BY period",
            [product.value, region.value, segment.value],
        ).fetchall()
        return [
            PricingActionRecord(
                period=row[0],
                product=Product(row[1]),
                region=Region(row[2]),
                segment=Segment(row[3]),
                price_change_pct=row[4],
                rationale=row[5],
                conversion_impact_pct=row[6],
                loss_ratio_impact_pct=row[7],
            )
            for row in rows
        ]


def _load_dataset(connection: duckdb.DuckDBPyConnection, dataset: ScenarioDataset) -> None:
    connection.execute(
        "CREATE TABLE claims (period DATE, product VARCHAR, region VARCHAR, segment VARCHAR, "
        "policies_in_force INTEGER, claim_count INTEGER, incurred_loss_gbp DOUBLE, "
        "earned_premium_gbp DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.period,
                r.product.value,
                r.region.value,
                r.segment.value,
                r.policies_in_force,
                r.claim_count,
                r.incurred_loss_gbp,
                r.earned_premium_gbp,
            )
            for r in dataset.claims
        ],
    )

    connection.execute(
        "CREATE TABLE conversion (period DATE, product VARCHAR, region VARCHAR, segment VARCHAR, "
        "quotes INTEGER, sales INTEGER, renewals_due INTEGER, renewals_retained INTEGER, "
        "average_quoted_premium_gbp DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO conversion VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.period,
                r.product.value,
                r.region.value,
                r.segment.value,
                r.quotes,
                r.sales,
                r.renewals_due,
                r.renewals_retained,
                r.average_quoted_premium_gbp,
            )
            for r in dataset.conversion
        ],
    )

    connection.execute(
        "CREATE TABLE competitors (period DATE, region VARCHAR, competitor_name VARCHAR, "
        "price_index DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO competitors VALUES (?, ?, ?, ?)",
        [
            (r.period, r.region.value, r.competitor_name, r.price_index)
            for r in dataset.competitors
        ],
    )

    connection.execute(
        "CREATE TABLE pricing_history (period DATE, product VARCHAR, region VARCHAR, "
        "segment VARCHAR, price_change_pct DOUBLE, rationale VARCHAR, "
        "conversion_impact_pct DOUBLE, loss_ratio_impact_pct DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO pricing_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.period,
                r.product.value,
                r.region.value,
                r.segment.value,
                r.price_change_pct,
                r.rationale,
                r.conversion_impact_pct,
                r.loss_ratio_impact_pct,
            )
            for r in dataset.pricing_history
        ],
    )
