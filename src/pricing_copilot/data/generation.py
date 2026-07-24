from __future__ import annotations

import random
from datetime import date

from pricing_copilot.contracts import Product, Region, ScenarioName, Segment
from pricing_copilot.data.records import (
    ClaimsMonthlyRecord,
    CompetitorMonthlyRecord,
    ConversionMonthlyRecord,
    PricingActionRecord,
    ScenarioDataset,
)

DEFAULT_SCENARIO_SEED = 20260101
DEFAULT_SCENARIO_VERSION = "v1"

TOTAL_MONTHS = 24
SCENARIO_START_MONTH = date(2024, 1, 1)

COMPETITOR_BASE_INDEX: dict[str, float] = {
    "Meridian Insure": 100.0,
    "Northgate Cover": 97.0,
    "Bracken Mutual": 103.0,
}


def _month_periods(start: date, count: int) -> list[date]:
    periods: list[date] = []
    year, month = start.year, start.month
    for _ in range(count):
        periods.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def _jitter(rng: random.Random, base: float, pct: float) -> float:
    return base * (1 + rng.uniform(-pct, pct))


def _generate_claims(rng: random.Random, periods: list[date]) -> list[ClaimsMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_current = index >= 12
        policies = round(_jitter(rng, 5000, 0.01))
        claim_count = round(_jitter(rng, 420, 0.03))
        severity_target = 1606.0 * 1.16 if is_current else 1606.0
        severity = _jitter(rng, severity_target, 0.02)
        earned_premium = round(_jitter(rng, 950_000.0, 0.01), 2)
        records.append(
            ClaimsMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                policies_in_force=policies,
                claim_count=claim_count,
                incurred_loss_gbp=round(claim_count * severity, 2),
                earned_premium_gbp=earned_premium,
            )
        )
    return records


def _generate_conversion(rng: random.Random, periods: list[date]) -> list[ConversionMonthlyRecord]:
    records = []
    segment_config: tuple[tuple[Segment, float, float | None], ...] = (
        (Segment.RENEWAL, 0.22, 0.88),
        (Segment.NEW_BUSINESS, 0.15, None),
    )
    for segment, base_conversion, base_retention in segment_config:
        for period in periods:
            quotes = round(_jitter(rng, 10_000, 0.02))
            sales = round(quotes * _jitter(rng, base_conversion, 0.03))
            if base_retention is not None:
                renewals_due = round(_jitter(rng, 4_000, 0.02))
                renewals_retained = round(renewals_due * _jitter(rng, base_retention, 0.02))
            else:
                renewals_due = 0
                renewals_retained = 0
            premium = round(_jitter(rng, 620.0, 0.01), 2)
            records.append(
                ConversionMonthlyRecord(
                    period=period,
                    product=Product.PERSONAL_MOTOR,
                    region=Region.NORTH_WEST,
                    segment=segment,
                    quotes=quotes,
                    sales=sales,
                    renewals_due=renewals_due,
                    renewals_retained=renewals_retained,
                    average_quoted_premium_gbp=premium,
                )
            )
    return records


def _generate_competitors(
    rng: random.Random, periods: list[date]
) -> list[CompetitorMonthlyRecord]:
    records = []
    for name, base_index in COMPETITOR_BASE_INDEX.items():
        for index, period in enumerate(periods):
            is_current = index >= 12
            target = base_index * (1.025 if is_current else 1.0)
            records.append(
                CompetitorMonthlyRecord(
                    period=period,
                    region=Region.NORTH_WEST,
                    competitor_name=name,
                    price_index=round(_jitter(rng, target, 0.01), 2),
                )
            )
    return records


def _generate_pricing_history(periods: list[date]) -> list[PricingActionRecord]:
    return [
        PricingActionRecord(
            period=periods[5],
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            price_change_pct=2.0,
            rationale=(
                "Portfolio-level 2% renewal price increase applied to offset early "
                "claims-inflation signals."
            ),
            conversion_impact_pct=-0.6,
            loss_ratio_impact_pct=-1.0,
        )
    ]


def _generate_controlled_increase_dataset(seed: int, version: str) -> ScenarioDataset:
    # Deliberately non-cryptographic: reproducibility from a fixed seed is the requirement.
    rng = random.Random(seed)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, TOTAL_MONTHS)
    return ScenarioDataset(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        seed=seed,
        version=version,
        claims=_generate_claims(rng, periods),
        conversion=_generate_conversion(rng, periods),
        competitors=_generate_competitors(rng, periods),
        pricing_history=_generate_pricing_history(periods),
    )


def _generate_retention_concern_claims(
    rng: random.Random, periods: list[date]
) -> list[ClaimsMonthlyRecord]:
    records = []
    for period in periods:
        policies = round(_jitter(rng, 5000, 0.01))
        claim_count = round(_jitter(rng, 420, 0.03))
        severity = _jitter(rng, 1606.0, 0.02)  # stable target across both windows
        earned_premium = round(_jitter(rng, 950_000.0, 0.01), 2)
        records.append(
            ClaimsMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                policies_in_force=policies,
                claim_count=claim_count,
                incurred_loss_gbp=round(claim_count * severity, 2),
                earned_premium_gbp=earned_premium,
            )
        )
    return records


def _generate_retention_concern_conversion(
    rng: random.Random, periods: list[date]
) -> list[ConversionMonthlyRecord]:
    records = []
    # (segment, baseline_conversion, current_conversion, baseline_retention, current_retention)
    segment_config: tuple[tuple[Segment, float, float, float | None, float | None], ...] = (
        (Segment.RENEWAL, 0.22, 0.19, 0.88, 0.74),
        (Segment.NEW_BUSINESS, 0.15, 0.15, None, None),
    )
    for segment, base_conv, current_conv, base_ret, current_ret in segment_config:
        for index, period in enumerate(periods):
            is_current = index >= 12
            conv_target = current_conv if is_current else base_conv
            quotes = round(_jitter(rng, 10_000, 0.02))
            sales = round(quotes * _jitter(rng, conv_target, 0.03))
            if base_ret is not None and current_ret is not None:
                ret_target = current_ret if is_current else base_ret
                renewals_due = round(_jitter(rng, 4_000, 0.02))
                renewals_retained = round(renewals_due * _jitter(rng, ret_target, 0.02))
            else:
                renewals_due = 0
                renewals_retained = 0
            premium = round(_jitter(rng, 620.0, 0.01), 2)
            records.append(
                ConversionMonthlyRecord(
                    period=period,
                    product=Product.PERSONAL_MOTOR,
                    region=Region.NORTH_WEST,
                    segment=segment,
                    quotes=quotes,
                    sales=sales,
                    renewals_due=renewals_due,
                    renewals_retained=renewals_retained,
                    average_quoted_premium_gbp=premium,
                )
            )
    return records


def _generate_retention_concern_competitors(
    rng: random.Random, periods: list[date]
) -> list[CompetitorMonthlyRecord]:
    records = []
    for name, base_index in COMPETITOR_BASE_INDEX.items():
        for index, period in enumerate(periods):
            is_current = index >= 12
            target = base_index * (0.95 if is_current else 1.0)
            records.append(
                CompetitorMonthlyRecord(
                    period=period,
                    region=Region.NORTH_WEST,
                    competitor_name=name,
                    price_index=round(_jitter(rng, target, 0.01), 2),
                )
            )
    return records


def _generate_retention_concern_pricing_history(periods: list[date]) -> list[PricingActionRecord]:
    return [
        PricingActionRecord(
            period=periods[5],
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            price_change_pct=2.0,
            rationale=(
                "Portfolio-level 2% renewal price increase applied earlier this year; retention "
                "softened materially in the months that followed."
            ),
            conversion_impact_pct=-8.0,
            loss_ratio_impact_pct=-0.5,
        )
    ]


def _generate_retention_concern_dataset(seed: int, version: str) -> ScenarioDataset:
    rng = random.Random(seed)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, TOTAL_MONTHS)
    return ScenarioDataset(
        scenario=ScenarioName.RETENTION_CONCERN,
        seed=seed,
        version=version,
        claims=_generate_retention_concern_claims(rng, periods),
        conversion=_generate_retention_concern_conversion(rng, periods),
        competitors=_generate_retention_concern_competitors(rng, periods),
        pricing_history=_generate_retention_concern_pricing_history(periods),
    )


CONFLICTING_EVIDENCE_CONVERSION_MONTHS = 20


def _generate_conflicting_evidence_claims(
    rng: random.Random, periods: list[date]
) -> list[ClaimsMonthlyRecord]:
    records = []
    for index, period in enumerate(periods):
        is_current = index >= 12
        policies = round(_jitter(rng, 5000, 0.01))
        claim_count = round(_jitter(rng, 420, 0.03))
        severity_target = 1606.0 * 1.30 if is_current else 1606.0
        severity = _jitter(rng, severity_target, 0.02)
        earned_premium = round(_jitter(rng, 950_000.0, 0.01), 2)
        records.append(
            ClaimsMonthlyRecord(
                period=period,
                product=Product.PERSONAL_MOTOR,
                region=Region.NORTH_WEST,
                segment=Segment.RENEWAL,
                policies_in_force=policies,
                claim_count=claim_count,
                incurred_loss_gbp=round(claim_count * severity, 2),
                earned_premium_gbp=earned_premium,
            )
        )
    return records


def _generate_conflicting_evidence_conversion(
    rng: random.Random, periods: list[date]
) -> list[ConversionMonthlyRecord]:
    incomplete_periods = periods[:CONFLICTING_EVIDENCE_CONVERSION_MONTHS]
    records = []
    for segment, base_conversion, base_retention in (
        (Segment.RENEWAL, 0.20, 0.85),
        (Segment.NEW_BUSINESS, 0.14, None),
    ):
        for period in incomplete_periods:
            quotes = round(_jitter(rng, 10_000, 0.02))
            sales = round(quotes * _jitter(rng, base_conversion, 0.03))
            if base_retention is not None:
                renewals_due = round(_jitter(rng, 4_000, 0.02))
                renewals_retained = round(renewals_due * _jitter(rng, base_retention, 0.02))
            else:
                renewals_due = 0
                renewals_retained = 0
            premium = round(_jitter(rng, 620.0, 0.01), 2)
            records.append(
                ConversionMonthlyRecord(
                    period=period,
                    product=Product.PERSONAL_MOTOR,
                    region=Region.NORTH_WEST,
                    segment=segment,
                    quotes=quotes,
                    sales=sales,
                    renewals_due=renewals_due,
                    renewals_retained=renewals_retained,
                    average_quoted_premium_gbp=premium,
                )
            )
    return records


def _generate_conflicting_evidence_competitors(
    rng: random.Random, periods: list[date]
) -> list[CompetitorMonthlyRecord]:
    records = []
    for name, base_index in COMPETITOR_BASE_INDEX.items():
        for index, period in enumerate(periods):
            is_current = index >= 12
            target = base_index * (1.01 if is_current else 1.0)
            records.append(
                CompetitorMonthlyRecord(
                    period=period,
                    region=Region.NORTH_WEST,
                    competitor_name=name,
                    price_index=round(_jitter(rng, target, 0.01), 2),
                )
            )
    return records


def _generate_conflicting_evidence_pricing_history(
    periods: list[date],
) -> list[PricingActionRecord]:
    return [
        PricingActionRecord(
            period=periods[5],
            product=Product.PERSONAL_MOTOR,
            region=Region.NORTH_WEST,
            segment=Segment.RENEWAL,
            price_change_pct=1.5,
            rationale=(
                "Small portfolio-level adjustment applied earlier this year; outcome data is "
                "inconclusive given gaps in the tracking period."
            ),
            conversion_impact_pct=-1.0,
            loss_ratio_impact_pct=0.0,
        )
    ]


def _generate_conflicting_evidence_dataset(seed: int, version: str) -> ScenarioDataset:
    rng = random.Random(seed)  # nosec B311
    periods = _month_periods(SCENARIO_START_MONTH, TOTAL_MONTHS)
    return ScenarioDataset(
        scenario=ScenarioName.CONFLICTING_EVIDENCE,
        seed=seed,
        version=version,
        claims=_generate_conflicting_evidence_claims(rng, periods),
        conversion=_generate_conflicting_evidence_conversion(rng, periods),
        competitors=_generate_conflicting_evidence_competitors(rng, periods),
        pricing_history=_generate_conflicting_evidence_pricing_history(periods),
    )


def generate_scenario_dataset(
    scenario: ScenarioName,
    seed: int = DEFAULT_SCENARIO_SEED,
    version: str = DEFAULT_SCENARIO_VERSION,
) -> ScenarioDataset:
    if scenario is ScenarioName.CONTROLLED_INCREASE:
        return _generate_controlled_increase_dataset(seed, version)
    if scenario is ScenarioName.RETENTION_CONCERN:
        return _generate_retention_concern_dataset(seed, version)
    if scenario is ScenarioName.CONFLICTING_EVIDENCE:
        return _generate_conflicting_evidence_dataset(seed, version)
    raise NotImplementedError(f"No generator implemented yet for scenario '{scenario.value}'.")
