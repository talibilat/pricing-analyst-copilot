from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st
from pydantic import ValidationError

from pricing_copilot.chat.contracts import (
    ChatActivity,
    ChatContext,
    ChatIntent,
    ChatResponse,
    ChatTable,
)
from pricing_copilot.chat.service import ChatService
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import (
    AnalystDecisionType,
    DecisionRequest,
    ResultSource,
    WorkflowResult,
)
from pricing_copilot.decisions.service import get_decision_store, record_analyst_decision
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.evidence.models import FairValueStatus


def _render_time_series(
    months: Sequence[date], series: dict[str, Sequence[float]], *, y_label: str
) -> None:
    values = [value for observations in series.values() for value in observations]
    if not months or not values:
        return
    minimum = min(values)
    maximum = max(values)
    padding = max((maximum - minimum) * 0.08, abs(maximum) * 0.01, 0.01)
    frame = pd.DataFrame({"month": months, **series}).melt(
        id_vars="month", var_name="series", value_name="value"
    )
    chart = (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:T", title="Month"),
            y=alt.Y(
                "value:Q",
                title=y_label,
                scale=alt.Scale(domain=[minimum - padding, maximum + padding]),
            ),
            color=alt.Color("series:N", title=None),
            tooltip=["month:T", "series:N", alt.Tooltip("value:Q", title=y_label)],
        )
    )
    st.altair_chart(chart, width="stretch")


def _render_table(table: ChatTable) -> None:
    st.markdown(f"**{table.title}**")
    st.dataframe(pd.DataFrame(table.rows, columns=table.columns), width="stretch", hide_index=True)


def _render_workflow_result(result: WorkflowResult) -> None:
    recommendation = result.recommendation
    st.caption(
        "System recommendation - policy-approved for qualified analyst review where shown. "
        "This is not a claim of regulatory compliance."
    )
    if recommendation.price_range is None:
        action = recommendation.action.value
    else:
        action = (
            f"{recommendation.action.value} "
            f"({recommendation.price_range.lower_pct:g}% to "
            f"{recommendation.price_range.upper_pct:g}%)"
        )
    st.markdown(f"**Proposed action:** {action}")
    st.markdown("**Reasoning**")
    st.write(recommendation.rationale)
    if recommendation.counter_evidence:
        st.markdown("**Counter-evidence**")
        st.write("\n".join(f"- {item}" for item in recommendation.counter_evidence))
    if recommendation.investigation_areas:
        st.markdown("**Areas to investigate**")
        st.write("\n".join(f"- {item}" for item in recommendation.investigation_areas))
    if recommendation.cited_evidence_ids:
        st.caption("Citations: " + ", ".join(recommendation.cited_evidence_ids))

    if recommendation.confidence is not None:
        confidence = recommendation.confidence
        st.markdown("**Confidence**")
        cols = st.columns(5)
        labels_and_values = [
            ("Evidence coverage", confidence.evidence_coverage),
            ("Source freshness", confidence.source_freshness),
            ("Specialist agreement", confidence.specialist_agreement),
            ("Data quality", confidence.data_quality),
            ("Conflict penalty", confidence.conflict_penalty),
        ]
        for column, (label, value) in zip(cols, labels_and_values, strict=True):
            column.metric(label, f"{value * 100:.0f}%")
        st.caption(f"Overall confidence: {confidence.overall * 100:.0f}%")

    if recommendation.fair_value_status is not None:
        fair_value_labels = {
            FairValueStatus.NO_CONCERN: "No concern",
            FairValueStatus.REVIEW_RECOMMENDED: "Review recommended",
            FairValueStatus.CONCERN_IDENTIFIED: "Concern identified",
        }
        st.markdown(
            f"**Fair value status:** {fair_value_labels[recommendation.fair_value_status]}"
        )
        if recommendation.fair_value_follow_up:
            st.write("\n".join(f"- {item}" for item in recommendation.fair_value_follow_up))

    analytics = result.analytics
    if analytics is None:
        return
    with st.expander("Supporting charts", expanded=False):
        st.caption("Claims performance")
        _render_time_series(
            [item.period for item in analytics.claims.loss_ratio.monthly],
            {"Loss ratio (%)": [item.value * 100 for item in analytics.claims.loss_ratio.monthly]},
            y_label="Loss ratio (%)",
        )
        st.caption("Conversion performance")
        _render_time_series(
            [item.period for item in analytics.conversion.quote_to_sale_conversion.monthly],
            {
                "Quote-to-sale conversion (%)": [
                    item.value * 100
                    for item in analytics.conversion.quote_to_sale_conversion.monthly
                ],
                "Renewal retention (%)": [
                    item.value * 100 for item in analytics.conversion.renewal_retention.monthly
                ],
            },
            y_label="Rate (%)",
        )


def _render_decision_controls(result: WorkflowResult, message_number: int) -> None:
    with st.expander("Confirm and record an analyst decision", expanded=False):
        st.caption(
            "This records your decision and rationale in the separate SQLite decision log. "
            "It does not execute a pricing change."
        )
        key_prefix = f"decision_{message_number}"
        decision = st.selectbox(
            "Your decision",
            options=list(AnalystDecisionType),
            format_func=lambda choice: choice.value,
            key=f"{key_prefix}_type",
        )
        rationale = st.text_area("Your rationale", key=f"{key_prefix}_rationale")
        conditions = st.text_area(
            "Conditions or outstanding questions, one per line",
            key=f"{key_prefix}_conditions",
        )
        confirmed = st.checkbox(
            "I confirm this is an analyst decision and does not execute a pricing action.",
            key=f"{key_prefix}_confirmed",
        )
        if st.button("Record analyst decision", key=f"{key_prefix}_submit", disabled=not confirmed):
            if not isinstance(decision, AnalystDecisionType):
                raise TypeError("Decision selector must return an analyst decision type.")
            request = DecisionRequest(
                question=result.question,
                recommendation=result.recommendation,
                governance_outcome=result.governance_outcome,
                decision=decision,
                rationale=rationale,
                conditions=[line.strip() for line in conditions.splitlines() if line.strip()],
            )
            try:
                recorded = record_analyst_decision(request, get_settings(), get_decision_store())
            except ValidationError as exc:
                st.error(f"Cannot record the decision: {exc}")
            else:
                st.success(f"Analyst decision recorded with id {recorded.record_id}.")


def _render_response(response: ChatResponse, message_number: int, *, can_record: bool) -> None:
    if response.source is ResultSource.REPLAY:
        st.warning(
            "REPLAY MODE - this is a cached, previously validated run, not a live analysis.",
            icon="🔁",
        )
    st.markdown(response.message)
    for table in response.tables:
        _render_table(table)
    if response.workflow_result is not None:
        _render_workflow_result(response.workflow_result)
        if can_record:
            _render_decision_controls(response.workflow_result, message_number)


def _render_drift_monitoring_tab() -> None:
    from pricing_copilot.drift.store import load_drift_report

    st.subheader("Drift and change-promotion monitoring")
    report = load_drift_report(get_settings())
    if report is None:
        st.info(
            "No drift monitoring run has been recorded yet. Run "
            "`pricing-copilot --monitor-drift` to generate one."
        )
        return
    st.caption(f"Generated {report.generated_at.isoformat()} - {report.report_version}")
    material = report.material_alerts
    if material:
        st.warning(f"{len(material)} measure(s) require investigation.", icon="⚠️")
    else:
        st.success("No material drift detected in the latest run.")
    for category in DriftAlertCategory:
        category_alerts = [alert for alert in report.alerts if alert.category is category]
        if not category_alerts:
            continue
        with st.expander(
            f"{category.value.title()} alerts ({len(category_alerts)})", expanded=bool(material)
        ):
            for alert in category_alerts:
                if alert.investigation_required:
                    status = "🔴 investigation required"
                elif alert.insufficient_sample:
                    status = "🟡 insufficient sample"
                else:
                    status = "🟢 normal"
                st.markdown(f"**{alert.metric_name}** - {status}")
                st.caption(f"Baseline: {alert.baseline_window} | Current: {alert.current_window}")
                st.write(alert.detail)
                for measurement in alert.measurements:
                    st.caption(
                        f"{measurement.measure_kind.value}: {measurement.value:g} "
                        f"{measurement.unit} (threshold {measurement.threshold:g}, "
                        f"{'breached' if measurement.breached else 'within range'})"
                    )


def _activity_text(activity: ChatActivity) -> str:
    duration = f" - {activity.duration_ms:g} ms" if activity.duration_ms is not None else ""
    return f"{activity.status.value.title()}: {activity.label}{duration}"


st.set_page_config(page_title="Pricing Decision Copilot", layout="wide")
st.title("Pricing Decision Copilot")
st.caption(
    "Chat-first, governed portfolio decision support. The copilot retrieves only permitted "
    "portfolio-level data and never executes a pricing change."
)

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = [
        {
            "role": "assistant",
            "response": ChatResponse(
                intent=ChatIntent.HELP,
                context=ChatContext(),
                message=(
                    "Ask me about claims, conversion, competitors, previous pricing actions, "
                    "market intelligence, or aggregate customer feedback. You can also ask for a "
                    "pricing recommendation or say ‘analyse everything’."
                ),
            ).model_dump(mode="json"),
        }
    ]

with st.sidebar:
    st.subheader("Suggested questions")
    st.caption("Type or paste one into the chat.")
    st.code("Show claims and conversion performance")
    st.code("What did competitors do in the retention concern scenario?")
    st.code("Analyse everything and recommend a pricing action")
    st.caption("Each run shows safe activity labels, not hidden prompts or private reasoning.")

tab_chat, tab_monitoring = st.tabs(["Chat", "Monitoring"])

with tab_chat:
    for message_number, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(message["role"]):
            response = ChatResponse.model_validate(message["response"])
            _render_response(response, message_number, can_record=False)

    if prompt := st.chat_input(
        "Ask a portfolio-level pricing question",
        key="pricing_chat_input",
        max_chars=1_000,
        submit_mode="disable",
    ):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.chat_messages.append(
            {
                "role": "user",
                "response": ChatResponse(
                    intent=ChatIntent.HELP, context=ChatContext(), message=prompt
                ).model_dump(mode="json"),
            }
        )
        with st.chat_message("assistant"):
            activity_box = st.empty()
            activity_lines: list[str] = []

            def show_activity(activity: ChatActivity) -> None:
                activity_lines.append(_activity_text(activity))
                activity_box.markdown("  \n".join(activity_lines[-10:]))

            with st.spinner("Working with governed portfolio sources..."):
                response = ChatService().submit(prompt, on_activity=show_activity)
            activity_box.empty()
            if "Live analysis could not complete" in response.message:
                message_number = len(st.session_state.chat_messages)
                if st.button("Try replay instead", key=f"replay_retry_{message_number}"):
                    retry_context = ChatContext(
                        scenario=response.context.scenario, force_replay=True
                    )
                    response = ChatService().submit(
                        prompt, retry_context, on_activity=show_activity
                    )
            if response.activities:
                with st.expander("Activity trace", expanded=True):
                    st.write(
                        "\n".join(
                            f"- {_activity_text(activity)}" for activity in response.activities
                        )
                    )
            message_number = len(st.session_state.chat_messages)
            _render_response(response, message_number, can_record=True)
        st.session_state.chat_messages.append(
            {"role": "assistant", "response": response.model_dump(mode="json")}
        )

with tab_monitoring:
    _render_drift_monitoring_tab()
