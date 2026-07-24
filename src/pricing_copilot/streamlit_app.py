from __future__ import annotations

from datetime import date

import streamlit as st

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.workflow import run_portfolio_workflow

st.set_page_config(page_title="Pricing Decision Copilot", layout="wide")
st.title("Pricing Decision Copilot")
st.caption(
    "Governed decision-support prototype. This build has no evidence sources connected, "
    "so every supported question safely returns an investigate outcome."
)

with st.form("portfolio_question"):
    col1, col2, col3 = st.columns(3)
    product = col1.selectbox("Product", options=list(Product), format_func=lambda p: p.value)
    region = col2.selectbox("Region", options=list(Region), format_func=lambda r: r.value)
    segment = col3.selectbox("Segment", options=list(Segment), format_func=lambda s: s.value)

    col4, col5 = st.columns(2)
    start_month = col4.date_input("Analysis start month", value=date(2026, 1, 1))
    end_month = col5.date_input("Analysis end month", value=date(2026, 6, 1))

    scenario_choice = st.selectbox(
        "Scenario (optional)",
        options=[None, *list(ScenarioName)],
        format_func=lambda s: "None" if s is None else s.value,
    )

    submitted = st.form_submit_button("Run analysis")

if submitted:
    if (
        not isinstance(product, Product)
        or not isinstance(region, Region)
        or not isinstance(segment, Segment)
    ):
        raise TypeError("Product, region, and segment selectors must always return a value.")

    try:
        question = PortfolioQuestion(
            product=product,
            region=region,
            segment=segment,
            analysis_period=AnalysisPeriod(start_month=start_month, end_month=end_month),
            scenario=scenario_choice,
        )
        result = run_portfolio_workflow(question)
    except UnsupportedPortfolioError as exc:
        st.error(str(exc))
    else:
        st.subheader(f"Recommendation: {result.recommendation.action.value}")
        st.write(result.recommendation.rationale)

        if result.analytics is not None:
            analytics = result.analytics

            st.subheader("Loss ratio (%)")
            st.line_chart(
                {"loss_ratio_pct": [v.value * 100 for v in analytics.claims.loss_ratio.monthly]}
            )

            st.subheader("Claim severity (GBP)")
            st.line_chart(
                {
                    "average_severity_gbp": [
                        v.value for v in analytics.claims.average_severity_gbp.monthly
                    ]
                }
            )

            st.subheader("Conversion and retention (%)")
            st.line_chart(
                {
                    "quote_to_sale_conversion_pct": [
                        v.value * 100 for v in analytics.conversion.quote_to_sale_conversion.monthly
                    ],
                    "renewal_retention_pct": [
                        v.value * 100 for v in analytics.conversion.renewal_retention.monthly
                    ],
                }
            )

            st.subheader("Competitor price-index movement")
            st.line_chart(
                {
                    movement.competitor_name: [v.value for v in movement.price_index.monthly]
                    for movement in analytics.competitors.competitors
                }
            )

            st.subheader("Pricing history")
            for action in analytics.pricing_history:
                st.write(
                    f"- **{action.period.isoformat()}**: {action.price_change_pct:+.1f}% - "
                    f"{action.rationale} (conversion impact {action.conversion_impact_pct:+.1f}%, "
                    f"loss-ratio impact {action.loss_ratio_impact_pct:+.1f}%)"
                )
        else:
            st.subheader("Missing evidence")
            for item in result.missing_evidence:
                st.warning(f"**{item.domain.value}**: {item.reason}")

        st.subheader("Specialist reports")
        for report in result.specialist_reports:
            st.write(f"- **{report.domain.value}** ({report.status}): {report.summary}")

        st.subheader("Governance outcome")
        st.json(result.governance_outcome.model_dump())
