from __future__ import annotations

import re

from pricing_copilot.config import PolicySettings
from pricing_copilot.contracts import EvidenceDomain, RecommendationAction, SpecialistReport
from pricing_copilot.evidence.models import EvidenceLedger
from pricing_copilot.recommendation.contracts import RecommendationDraft

_CUSTOMER_LEVEL_PATTERN = re.compile(
    r"\b(?:individual|specific|named|per)[ -](?:customer|policyholder|policy)\b"
    r"|\bcustomer-level\b|\bpolicyholder-level\b",
    re.IGNORECASE,
)


def validate_pre_synthesis_policy(
    *,
    specialist_reports: list[SpecialistReport],
    ledger: EvidenceLedger,
    policy: PolicySettings,
) -> list[str]:
    issues: list[str] = []
    completed = {report.domain for report in specialist_reports if report.status == "completed"}
    if policy.require_claims_evidence and EvidenceDomain.CLAIMS not in completed:
        issues.append("claims: required claims evidence is missing.")
    if policy.require_conversion_evidence and EvidenceDomain.CONVERSION not in completed:
        issues.append("conversion: required conversion evidence is missing.")

    source_types = {entry.source_type for entry in ledger.entries}
    if len(source_types) < policy.minimum_source_types:
        issues.append(
            f"evidence: {len(source_types)} source type(s) are available, below the configured "
            f"minimum of {policy.minimum_source_types}."
        )
    return issues


def validate_recommendation_scope(
    draft: RecommendationDraft, policy: PolicySettings
) -> list[str]:
    issues: list[str] = []
    texts = [
        draft.rationale,
        *draft.counter_evidence,
        *draft.conditions,
        *draft.investigation_areas,
    ]
    if policy.prohibit_customer_level_actions and any(
        _CUSTOMER_LEVEL_PATTERN.search(text) for text in texts
    ):
        issues.append("Recommendation proposes or describes a prohibited customer-level action.")
    prohibited: list[str] = []
    for attribute in policy.prohibited_attributes:
        if attribute == "age":
            pattern = re.compile(
                r"\b(?:customer|policyholder|pricing|segment(?:ation)?)"
                r".{0,20}\bage\b|\bage[- ]based\b",
                re.IGNORECASE,
            )
        else:
            pattern = re.compile(rf"\b{re.escape(attribute)}\b", re.IGNORECASE)
        if any(pattern.search(text) for text in texts):
            prohibited.append(attribute)
    if prohibited:
        issues.append(
            "Recommendation references prohibited protected attributes: "
            f"{', '.join(sorted(prohibited))}."
        )
    if draft.action in (RecommendationAction.HOLD, RecommendationAction.INVESTIGATE):
        if draft.price_range is not None:
            issues.append(f"{draft.action.value} must not include a price range.")
    elif draft.price_range is None:
        issues.append(f"{draft.action.value} requires a bounded price range.")
    elif draft.action is RecommendationAction.INCREASE and draft.price_range.lower_pct < 0:
        issues.append("Increase ranges cannot include a negative movement.")
    elif draft.action is RecommendationAction.DECREASE and draft.price_range.upper_pct > 0:
        issues.append("Decrease ranges cannot include a positive movement.")
    return issues


def human_approval_condition(policy: PolicySettings) -> str | None:
    if not policy.require_human_approval:
        return None
    return (
        "Requires explicit approval from a qualified pricing analyst before any action; "
        "the copilot cannot execute a pricing change."
    )
