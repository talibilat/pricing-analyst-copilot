from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from pricing_copilot.contracts import Product, Region, ScenarioName, Segment


class ClaimsMonthlyRecord(BaseModel):
    period: date
    product: Product
    region: Region
    segment: Segment
    policies_in_force: int
    claim_count: int
    incurred_loss_gbp: float
    earned_premium_gbp: float


class ConversionMonthlyRecord(BaseModel):
    period: date
    product: Product
    region: Region
    segment: Segment
    quotes: int
    sales: int
    renewals_due: int
    renewals_retained: int
    average_quoted_premium_gbp: float


class CompetitorMonthlyRecord(BaseModel):
    period: date
    region: Region
    competitor_name: str
    price_index: float


class PricingActionRecord(BaseModel):
    period: date
    product: Product
    region: Region
    segment: Segment
    price_change_pct: float
    rationale: str
    conversion_impact_pct: float
    loss_ratio_impact_pct: float


class ScenarioDataset(BaseModel):
    scenario: ScenarioName
    seed: int
    version: str
    claims: list[ClaimsMonthlyRecord]
    conversion: list[ConversionMonthlyRecord]
    competitors: list[CompetitorMonthlyRecord]
    pricing_history: list[PricingActionRecord]
