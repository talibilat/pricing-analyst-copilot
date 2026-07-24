from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
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
