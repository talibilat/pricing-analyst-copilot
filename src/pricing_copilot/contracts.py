from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pricing_copilot.analytics.contracts import PortfolioAnalytics
from pricing_copilot.evidence.models import ConfidenceBreakdown, EvidenceLedger, FairValueStatus
from pricing_copilot.observability.contracts import WorkflowExecutionTrace


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
    DRIFT_MONITORING = "drift_monitoring"


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


class ResultSource(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


class AnalysisPeriod(BaseModel):
    start_month: date
    end_month: date

    @model_validator(mode="after")
    def check_ordering(self) -> AnalysisPeriod:
        if self.end_month < self.start_month:
            raise ValueError("end_month must not be before start_month")
        return self


class PortfolioQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    counter_evidence: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    investigation_areas: list[str] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceBreakdown | None = None
    fair_value_status: FairValueStatus | None = None
    fair_value_follow_up: list[str] = Field(default_factory=list)


class GovernanceOutcome(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)


class ConfigurationVersions(BaseModel):
    model_name: str
    recommendation_version: str
    governance_version: str
    scenario_seed: int
    scenario_version: str
    max_price_movement_pct: float
    prompt_version: str = "governed-prompts-v1"
    agent_registry_version: str = "approved-agent-registry-v1"
    tool_version: str = "deterministic-tools-v1"
    dataset_version: str = "scenario-dataset-v1"
    recommendation_policy_version: str = "recommendation-policy-v1"
    output_schema_version: str = "workflow-result-schema-v1"


class AnalystDecision(BaseModel):
    record_id: str | None = None
    question: PortfolioQuestion
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    evidence_ids: list[str] = Field(default_factory=list)
    decision: AnalystDecisionType
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    decided_at: datetime
    configuration_versions: ConfigurationVersions
    source: ResultSource = ResultSource.LIVE

    @model_validator(mode="after")
    def check_material_decision_requirements(self) -> AnalystDecision:
        if not self.rationale.strip():
            raise ValueError("rationale is required for a material analyst decision.")
        needs_conditions = self.decision in (
            AnalystDecisionType.APPROVE_WITH_CONDITIONS,
            AnalystDecisionType.REQUEST_INVESTIGATION,
        )
        if needs_conditions and not any(c.strip() for c in self.conditions):
            raise ValueError(
                f"{self.decision.value} requires at least one recorded condition or "
                "outstanding question."
            )
        return self


class DecisionRequest(BaseModel):
    question: PortfolioQuestion
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    decision: AnalystDecisionType
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    source: ResultSource = ResultSource.LIVE


class WorkflowResult(BaseModel):
    question: PortfolioQuestion
    specialist_reports: list[SpecialistReport]
    recommendation: Recommendation
    governance_outcome: GovernanceOutcome
    missing_evidence: list[MissingEvidence]
    analytics: PortfolioAnalytics | None = None
    evidence_ledger: EvidenceLedger | None = None
    execution_trace: WorkflowExecutionTrace | None = None
    source: ResultSource = ResultSource.LIVE
