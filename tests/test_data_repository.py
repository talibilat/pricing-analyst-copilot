from pathlib import Path

from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.data.persistent import build_analytics_database
from pricing_copilot.data.repository import PortfolioDataRepository


def _repository() -> PortfolioDataRepository:
    return PortfolioDataRepository.from_scenario(
        ScenarioName.CONTROLLED_INCREASE, seed=42, version="v1"
    )


def test_fetch_claims_returns_24_ordered_records_for_supported_portfolio() -> None:
    repository = _repository()
    records = repository.fetch_claims(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    assert len(records) == 24
    assert [r.period for r in records] == sorted(r.period for r in records)


def test_fetch_conversion_returns_both_segments() -> None:
    repository = _repository()
    records = repository.fetch_conversion(Product.PERSONAL_MOTOR, Region.NORTH_WEST)
    segments = {r.segment for r in records}
    assert segments == {Segment.RENEWAL, Segment.NEW_BUSINESS}
    assert len(records) == 48


def test_fetch_competitors_returns_all_competitors_for_region() -> None:
    repository = _repository()
    records = repository.fetch_competitors(Region.NORTH_WEST)
    names = {r.competitor_name for r in records}
    assert len(names) == 3
    assert len(records) == 72


def test_fetch_pricing_history_returns_recorded_actions() -> None:
    repository = _repository()
    records = repository.fetch_pricing_history(
        Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
    )
    assert len(records) == 1
    assert records[0].price_change_pct == 2.0


def test_fetch_claims_for_unrecorded_region_returns_empty() -> None:
    repository = _repository()
    records = repository.fetch_claims(Product.PERSONAL_MOTOR, Region.SOUTH_EAST, Segment.RENEWAL)
    assert records == []


def test_from_persistent_returns_scenario_data(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.duckdb"
    build_analytics_database(path)

    repository = PortfolioDataRepository.from_persistent(ScenarioName.CONTROLLED_INCREASE, path)

    claims = repository.fetch_claims(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)
    assert len(claims) == 24
    assert [r.period for r in claims] == sorted(r.period for r in claims)

    conversion = repository.fetch_conversion(Product.PERSONAL_MOTOR, Region.NORTH_WEST)
    assert {r.segment for r in conversion} == {Segment.RENEWAL, Segment.NEW_BUSINESS}
    assert len(conversion) == 48

    competitors = repository.fetch_competitors(Region.NORTH_WEST)
    assert len({r.competitor_name for r in competitors}) == 3
    assert len(competitors) == 72

    pricing = repository.fetch_pricing_history(
        Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
    )
    assert len(pricing) == 1
    assert pricing[0].price_change_pct == 2.0


def test_from_persistent_isolates_scenarios_in_shared_file(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.duckdb"
    build_analytics_database(path)

    controlled = PortfolioDataRepository.from_persistent(ScenarioName.CONTROLLED_INCREASE, path)
    retention = PortfolioDataRepository.from_persistent(ScenarioName.RETENTION_CONCERN, path)

    controlled_claims = controlled.fetch_claims(
        Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
    )
    retention_claims = retention.fetch_claims(
        Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
    )

    # Both scenarios populate the same portfolio slice, but with distinct figures -
    # neither repository leaks the other's rows despite sharing one physical file.
    assert len(controlled_claims) == 24
    assert len(retention_claims) == 24
    assert [r.incurred_loss_gbp for r in controlled_claims] != [
        r.incurred_loss_gbp for r in retention_claims
    ]


def test_from_persistent_matches_deterministic_from_scenario(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.duckdb"
    build_analytics_database(path)

    for scenario in ScenarioName:
        persistent = PortfolioDataRepository.from_persistent(scenario, path)
        deterministic = PortfolioDataRepository.from_scenario(scenario)

        assert persistent.fetch_claims(
            Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
        ) == deterministic.fetch_claims(
            Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
        )
        assert persistent.fetch_conversion(
            Product.PERSONAL_MOTOR, Region.NORTH_WEST
        ) == deterministic.fetch_conversion(Product.PERSONAL_MOTOR, Region.NORTH_WEST)
        assert persistent.fetch_competitors(Region.NORTH_WEST) == deterministic.fetch_competitors(
            Region.NORTH_WEST
        )
        assert persistent.fetch_pricing_history(
            Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
        ) == deterministic.fetch_pricing_history(
            Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL
        )
