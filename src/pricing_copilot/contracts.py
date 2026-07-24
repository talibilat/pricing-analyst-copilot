from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from pricing_copilot.analytics.contracts import PortfolioAnalytics


class Product(StrEnum):
    PERSONAL_MOTOR = "personal_motor"


class Region(StrEnum):
    NORTH_WEST = "north_west"
    SOUTH_EAST = "south_east"


class Segment(StrEnum):
    RENEWAL = "renewal"
    NEW_BUSINESS = "new_business"


class ScenarioName(StrEnum):
    CONTROLLED_INCREASE = "controlled_increase"
    RETENTION_CONCERN = "retention_concern"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class EvidenceDomain(StrEnum):
    CLAIMS = "claims"
    CONVERSION = "conversion"
    MARKET_INTELLIGENCE = "market_intelligence"
    PRICING_HISTORY = "pricing_history"


class RecommendationAction(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    HOLD = "hold"
    INVESTIGATE = "investigate"


class AnalystDecisionType(StrEnum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    REJECT = "reject"
    REQUEST_INVESTIGATION = "request_investigation"


class AnalysisPeriod(BaseModel):
    start_month: date
    end_month: date

    @model_validator(mode="after")
    def check_ordering(self) -> AnalysisPeriod:
        if self.end_month < self.start_month:
            raise ValueError("end_month must not be before start_month")
        return self


class PortfolioQuestion(BaseModel):
    product: Product
    region: Region
    segment: Segment
    analysis_period: AnalysisPeriod
    scenario: ScenarioName | None = None


class MissingEvidence(BaseModel):
    domain: EvidenceDomain
    reason: str


class SpecialistReport(BaseModel):
    domain: EvidenceDomain
    status: str = Field(pattern="^(completed|missing_evidence|error)$")
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class PriceRange(BaseModel):
    lower_pct: float
    upper_pct: float

    @model_validator(mode="after")
    def check_bounds(self) -> PriceRange:
        if self.upper_pct < self.lower_pct:
            raise ValueError("upper_pct must not be below lower_pct")
        return self


class Recommendation(BaseModel):
    action: RecommendationAction
    price_range: PriceRange | None = None
    rationale: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class GovernanceOutcome(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)


class AnalystDecision(BaseModel):
    decision: AnalystDecisionType
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    decided_at: datetime


class WorkflowResult(BaseModel):
    question: PortfolioQuestion
    specialist_reports: list[SpecialistReport]
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    missing_evidence: list[MissingEvidence]
    analytics: PortfolioAnalytics | None = None
