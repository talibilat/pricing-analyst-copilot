from __future__ import annotations

from pricing_copilot.contracts import Product, Region, Segment

SUPPORTED_PORTFOLIOS: frozenset[tuple[Product, Region, Segment]] = frozenset(
    {
        (Product.PERSONAL_MOTOR, Region.NORTH_WEST, Segment.RENEWAL),
    }
)


class UnsupportedPortfolioError(ValueError):
    def __init__(self, product: Product, region: Region, segment: Segment) -> None:
        supported = ", ".join(
            f"{p.value}/{r.value}/{s.value}" for (p, r, s) in sorted(SUPPORTED_PORTFOLIOS)
        )
        message = (
            f"Unsupported portfolio combination: product={product.value}, "
            f"region={region.value}, segment={segment.value}. "
            f"This prototype currently supports: {supported}."
        )
        super().__init__(message)
        self.product = product
        self.region = region
        self.segment = segment


def validate_portfolio_combination(product: Product, region: Region, segment: Segment) -> None:
    if (product, region, segment) not in SUPPORTED_PORTFOLIOS:
        raise UnsupportedPortfolioError(product, region, segment)
