from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class MonthlyValue(BaseModel):
    period: date
    value: float


class WindowMetric(BaseModel):
    baseline: float
    current: float
    movement_pct: float | None
    monthly: list[MonthlyValue]


class ClaimsMetrics(BaseModel):
    period_start: date
    period_end: date
    claim_frequency: WindowMetric
    average_severity_gbp: WindowMetric
    incurred_loss_gbp: WindowMetric
    loss_ratio: WindowMetric


class ConversionMetrics(BaseModel):
    period_start: date
    period_end: date
    quote_to_sale_conversion: WindowMetric
    renewal_retention: WindowMetric
    average_quoted_premium_gbp: WindowMetric
    segment_comparison: dict[str, WindowMetric]


class CompetitorMovement(BaseModel):
    competitor_name: str
    price_index: WindowMetric
    rank: WindowMetric


class CompetitorMetrics(BaseModel):
    period_start: date
    period_end: date
    competitors: list[CompetitorMovement]


class PricingHistoryComparison(BaseModel):
    period: date
    price_change_pct: float
    rationale: str
    conversion_impact_pct: float
    loss_ratio_impact_pct: float


class PortfolioAnalytics(BaseModel):
    claims: ClaimsMetrics
    conversion: ConversionMetrics
    competitors: CompetitorMetrics
    pricing_history: list[PricingHistoryComparison] = Field(default_factory=list)
