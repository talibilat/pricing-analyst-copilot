from __future__ import annotations

from pydantic import BaseModel, Field

from pricing_copilot.contracts import PriceRange, RecommendationAction


class RecommendationDraft(BaseModel):
    action: RecommendationAction
    price_range: PriceRange | None = None
    rationale: str
    counter_evidence: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    investigation_areas: list[str] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
