from __future__ import annotations

from pydantic import BaseModel, Field


class SpecialistFindings(BaseModel):
    """A specialist agent's typed, validated output - interpretation plus citations only.

    No raw numbers are invented here: every number that appears in `summary` must have come
    from a deterministic tool call, and every id in `cited_evidence_ids` must be one the tool
    handed back.
    """

    summary: str
    cited_evidence_ids: list[str] = Field(default_factory=list)


class GovernanceReview(BaseModel):
    approved: bool
    feedback: str = ""
