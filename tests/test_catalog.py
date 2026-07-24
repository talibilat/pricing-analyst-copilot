import pytest

from pricing_copilot.catalog import UnsupportedPortfolioError, validate_portfolio_combination
from pricing_copilot.contracts import Product, Region, Segment


def test_supported_combination_does_not_raise() -> None:
    validate_portfolio_combination(Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL)


def test_unsupported_region_raises_with_clear_message() -> None:
    with pytest.raises(UnsupportedPortfolioError) as exc_info:
        validate_portfolio_combination(Product.PERSONAL_MOTOR, Region.SOUTH_EAST, Segment.RENEWAL)
    message = str(exc_info.value)
    assert "south_east" in message
    assert "north_west" in message  # names the supported alternative
