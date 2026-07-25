from __future__ import annotations

from datetime import date

import streamlit as st
from pydantic import ValidationError

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecisionType,
    DecisionRequest,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.decisions.service import get_decision_store, record_analyst_decision
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
        st.session_state.pop("workflow_result", None)
        st.session_state.pop("current_portfolio_question", None)
    else:
        st.session_state["workflow_result"] = result
        st.session_state["current_portfolio_question"] = question
        st.session_state.pop("decision_confirmation", None)

result = st.session_state.get("workflow_result")
question = st.session_state.get("current_portfolio_question")

if result is not None and question is not None:
    st.subheader("System recommendation")
    st.write(f"**{result.recommendation.action.value}**")
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

        recommendation = result.recommendation
        st.subheader("Proposed action")
        if recommendation.price_range is not None:
            st.write(
                f"**{recommendation.action.value}** "
                f"({recommendation.price_range.lower_pct:g}% to "
                f"{recommendation.price_range.upper_pct:g}%)"
            )
        else:
            st.write(f"**{recommendation.action.value}**")

        evidence_col, counter_col = st.columns(2)
        with evidence_col:
            st.markdown("**Supporting rationale**")
            st.write(recommendation.rationale)
        with counter_col:
            st.markdown("**Counter-evidence**")
            for item in recommendation.counter_evidence:
                st.write(f"- {item}")

        if recommendation.conditions:
            st.markdown("**Conditions**")
            for item in recommendation.conditions:
                st.write(f"- {item}")
        if recommendation.investigation_areas:
            st.markdown("**Areas for further investigation**")
            for item in recommendation.investigation_areas:
                st.write(f"- {item}")

        if recommendation.fair_value_status is not None:
            st.subheader(f"Fair-value status: {recommendation.fair_value_status.value}")
            for item in recommendation.fair_value_follow_up:
                st.write(f"- {item}")

        if recommendation.confidence is not None:
            st.subheader("Confidence components")
            st.json(recommendation.confidence.model_dump())

        with st.expander("Evidence ledger detail"):
            if result.evidence_ledger is not None:
                for entry in result.evidence_ledger.entries:
                    st.write(
                        f"- **{entry.evidence_id}** ({entry.source_type}): "
                        f"{entry.interpretation}"
                    )

        st.subheader("Pricing history")
        for action in analytics.pricing_history:
            st.write(
                f"- **{action.period.isoformat()}**: {action.price_change_pct:+.1f}% - "
                f"{action.rationale} (conversion impact {action.conversion_impact_pct:+.1f}%, "
                f"loss-ratio impact {action.loss_ratio_impact_pct:+.1f}%)"
            )

        st.subheader("Analyst review")
        st.caption(
            "This section records the analyst's decision. It does not change the system "
            "recommendation shown above, and it never executes a pricing change."
        )
        with st.form("analyst_review"):
            decision_choice = st.selectbox(
                "Decision",
                options=list(AnalystDecisionType),
                format_func=lambda d: d.value,
            )
            rationale_input = st.text_area("Rationale (required for every decision)")
            conditions_input = st.text_area(
                "Conditions or outstanding questions - one per line. Required for "
                "'approve_with_conditions' and 'request_investigation'."
            )
            decision_submitted = st.form_submit_button("Record analyst decision")

        if decision_submitted:
            if not isinstance(decision_choice, AnalystDecisionType):
                raise TypeError("Decision selector must always return a value.")

            conditions_list = [
                line.strip() for line in conditions_input.splitlines() if line.strip()
            ]
            request = DecisionRequest(
                question=question,
                recommendation=result.recommendation,
                governance_outcome=result.governance_outcome,
                decision=decision_choice,
                rationale=rationale_input,
                conditions=conditions_list,
            )
            try:
                recorded = record_analyst_decision(request, get_settings(), get_decision_store())
            except ValidationError as exc:
                st.error(f"Cannot record decision: {exc}")
            else:
                st.session_state["decision_confirmation"] = recorded

        confirmation = st.session_state.get("decision_confirmation")
        if confirmation is not None:
            st.success(
                f"Analyst decision recorded: **{confirmation.decision.value}** "
                f"(record id `{confirmation.record_id}`)."
            )

        with st.expander("Decision history for this portfolio"):
            history = get_decision_store().list_for_question(
                question.product, question.region, question.segment
            )
            if not history:
                st.write("No recorded decisions yet for this portfolio.")
            for record in history:
                st.write(
                    f"- **{record.decision.value}** at {record.decided_at.isoformat()} "
                    f"- {record.rationale}"
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
