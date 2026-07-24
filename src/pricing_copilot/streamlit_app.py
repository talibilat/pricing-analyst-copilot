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

        st.subheader("Missing evidence")
        for item in result.missing_evidence:
            st.warning(f"**{item.domain.value}**: {item.reason}")

        st.subheader("Specialist reports")
        for report in result.specialist_reports:
            st.write(f"- **{report.domain.value}** ({report.status}): {report.summary}")

        st.subheader("Governance outcome")
        st.json(result.governance_outcome.model_dump())
