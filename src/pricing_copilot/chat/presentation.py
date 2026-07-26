"""User-facing analytical composition for portfolio responses.

The workflow result remains the auditable decision-support record.  This module intentionally
turns that record into a short analyst answer instead of exposing tables, prompts, policy text,
or orchestration state as the primary response.
"""

from __future__ import annotations

from pricing_copilot.contracts import RecommendationAction, WorkflowResult


def _percentage(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "not comparable"
    return f"{value * 100:+.1f}%" if signed else f"{value * 100:.1f}%"


def _movement(value: float | None) -> str:
    return "not comparable" if value is None else f"{value:+.1f}%"


def _currency(value: float | None) -> str:
    return "not comparable" if value is None else f"£{value:,.0f}"


def _action_text(result: WorkflowResult) -> str:
    recommendation = result.recommendation
    if recommendation.action is RecommendationAction.INCREASE and recommendation.price_range:
        return (
            f"Recommend a controlled {recommendation.price_range.lower_pct:g}% to "
            f"{recommendation.price_range.upper_pct:g}% price increase, initially in a pilot."
        )
    if recommendation.action is RecommendationAction.DECREASE:
        return "Do not hold the current price level unchanged; test a targeted decrease."
    if recommendation.action is RecommendationAction.HOLD:
        return "Hold current pricing while the commercial risk is investigated."
    return "Do not change pricing yet; resolve the material uncertainty first."


def _direct_answer(
    result: WorkflowResult,
    *,
    focus: str | None,
    average_competitor_movement: float | None,
) -> str:
    analytics = result.analytics
    if analytics is None:
        return _action_text(result)
    if focus == "competitors" and average_competitor_movement is not None:
        return (
            f"Competitor price indices increased {average_competitor_movement:+.1f}% on average. "
            "That supports pricing headroom, but claims and conversion evidence remain necessary "
            "for a pricing decision."
        )
    if focus == "claims":
        return (
            f"Claims performance deteriorated: loss ratio moved "
            f"{_movement(analytics.claims.loss_ratio.movement_pct)} and average severity moved "
            f"{_movement(analytics.claims.average_severity_gbp.movement_pct)}."
        )
    if focus == "conversion":
        return (
            "Commercial performance remained resilient: quote-to-sale conversion moved "
            f"{_movement(analytics.conversion.quote_to_sale_conversion.movement_pct)}."
        )
    if focus == "pricing_history" and analytics.pricing_history:
        latest = analytics.pricing_history[-1]
        return (
            f"The latest recorded pricing action was {latest.price_change_pct:+.1f}%, with a "
            f"recorded conversion impact of {latest.conversion_impact_pct:+.1f}%."
        )
    return _action_text(result)


def compose_analysis_response(
    result: WorkflowResult,
    *,
    segment_identification_requested: bool = False,
    focus: str | None = None,
) -> str:
    """Compose an answer that explicitly distinguishes fact, judgement, and next action."""
    analytics = result.analytics
    if analytics is None:
        return (
            "I cannot produce a supported pricing conclusion from the available evidence. "
            "The next step is to restore the missing source and rerun the portfolio review."
        )

    claims = analytics.claims
    conversion = analytics.conversion
    competitors = analytics.competitors.competitors
    average_competitor_movement = (
        sum(item.price_index.movement_pct or 0.0 for item in competitors) / len(competitors)
        if competitors
        else None
    )
    segment_answer = (
        "Renewal is the observed segment with the loss-ratio deterioration. "
        "The supplied claims evidence contains renewal observations only, so this is a qualified "
        "identification rather than a comparison across every segment. "
        if segment_identification_requested
        else ""
    )
    evidence = [
        "Loss ratio moved from "
        f"{_percentage(claims.loss_ratio.baseline)} to {_percentage(claims.loss_ratio.current)} "
        f"({_movement(claims.loss_ratio.movement_pct)}).",
        "Average claim severity moved from "
        f"{_currency(claims.average_severity_gbp.baseline)} to "
        f"{_currency(claims.average_severity_gbp.current)} "
        f"({_movement(claims.average_severity_gbp.movement_pct)}).",
        "Quote-to-sale conversion moved from "
        f"{_percentage(conversion.quote_to_sale_conversion.baseline)} to "
        f"{_percentage(conversion.quote_to_sale_conversion.current)} "
        f"({_movement(conversion.quote_to_sale_conversion.movement_pct)}).",
    ]
    if conversion.renewal_retention.baseline is not None:
        evidence.append(
            "Renewal retention moved from "
            f"{_percentage(conversion.renewal_retention.baseline)} to "
            f"{_percentage(conversion.renewal_retention.current)} "
            f"({_movement(conversion.renewal_retention.movement_pct)})."
        )
    if average_competitor_movement is not None:
        evidence.append(
            f"Competitor price indices moved {average_competitor_movement:+.1f}% on average."
        )

    limitations: list[str] = []
    for item in result.missing_evidence:
        if item.domain.value == "market_intelligence":
            limitations.append(
                "Market evidence is stale or conflicting, so it cannot support a price movement "
                "until it is refreshed and reconciled."
            )
        else:
            limitations.append(item.reason.split(": ", maxsplit=1)[-1])
    for label, metric in (
        ("claims", claims.loss_ratio),
        ("conversion", conversion.quote_to_sale_conversion),
    ):
        if not metric.is_complete:
            limitations.append(
                f"{label.capitalize()} evidence covers {metric.observed_periods} of "
                f"{metric.expected_periods} requested months."
            )
    if result.recommendation.confidence is not None:
        confidence = f"{result.recommendation.confidence.overall * 100:.0f}%"
    else:
        confidence = "reduced" if limitations else "moderate"

    investigation = list(result.recommendation.investigation_areas)
    if not investigation:
        investigation = [
            "Review repair-cost and claim-settlement cohorts for the months where severity rose, "
            "and quantify their contribution to the loss-ratio movement before widening any pilot."
        ]
    limitation_lines = (
        [f"- {item}" for item in dict.fromkeys(limitations)]
        if limitations
        else ["- Evidence is complete for the requested window."]
    )
    recommendation = result.recommendation
    interpretation = recommendation.rationale
    if claims.loss_ratio.movement_pct and claims.loss_ratio.movement_pct > 0:
        interpretation += (
            " The claims trend is consistent with cost pressure; conversion should be monitored "
            "during any pricing test because it measures available commercial headroom, not "
            "causality."
        )

    lines = [
        "## Direct answer",
        segment_answer
        + _direct_answer(
            result, focus=focus, average_competitor_movement=average_competitor_movement
        ),
        "\n## Key evidence",
        *(f"- {item}" for item in evidence),
        "\n## Interpretation",
        interpretation,
        "\n## Recommended action",
        _action_text(result),
        *(
            f"- Condition: {item}"
            for item in recommendation.conditions
            if "approval" not in item.lower()
        ),
        "\n## Confidence and limitations",
        f"Confidence: {confidence}.",
        *limitation_lines,
        "\n## Specific next investigation",
        *(f"- {item}" for item in investigation),
    ]
    return "\n".join(lines)
