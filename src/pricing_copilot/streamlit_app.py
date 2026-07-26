from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from time import monotonic

import altair as alt
import pandas as pd
import streamlit as st
from pydantic import ValidationError

from pricing_copilot.chat.contracts import (
    ActivityStatus,
    ChatActivity,
    ChatContext,
    ChatIntent,
    ChatResponse,
    ChatTable,
    ConversationMessage,
)
from pricing_copilot.chat.history import conversation_history_message
from pricing_copilot.chat.service import ChatService
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    AnalystDecisionType,
    DecisionRequest,
    PortfolioQuestion,
    Product,
    Region,
    ResultSource,
    Segment,
    WorkflowResult,
)
from pricing_copilot.decisions.service import get_decision_store, record_analyst_decision
from pricing_copilot.drift.contracts import DriftAlertCategory
from pricing_copilot.evidence.models import EvidenceLedger
from pricing_copilot.streamlit_scroll import AUTO_SCROLL_SCRIPT
from pricing_copilot.streamlit_theme import (
    INJECT_CSS,
    assistant_avatar_data_uri,
    confidence_bars_html,
    portfolio_pill_text,
)


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


def _render_evidence_detail(ledger: EvidenceLedger, cited_ids: list[str]) -> None:
    cited_entries = [entry for entry in ledger.entries if entry.evidence_id in cited_ids]
    if not cited_entries:
        return
    with st.expander(f"Evidence detail ({len(cited_entries)})", expanded=False):
        for entry in cited_entries:
            st.markdown(f"**{entry.evidence_id}** - {entry.source_type}")
            detail_line = f"Source: {entry.source_reference}"
            if entry.source_date is not None:
                detail_line += f" | Date: {entry.source_date.isoformat()}"
            st.caption(detail_line)
            if entry.metric_name is not None:
                metric_line = f"{entry.metric_name}: {entry.value}"
                if entry.baseline_value is not None:
                    metric_line += f" (baseline {entry.baseline_value})"
                st.write(metric_line)
            st.write(entry.interpretation)
            st.divider()


def _render_workflow_result(result: WorkflowResult) -> None:
    recommendation = result.recommendation
    with st.expander("Supporting evidence and optional audit trace", expanded=False):
        if recommendation.cited_evidence_ids and result.evidence_ledger is not None:
            _render_evidence_detail(result.evidence_ledger, recommendation.cited_evidence_ids)
        if recommendation.confidence is not None:
            confidence = recommendation.confidence
            st.markdown(
                confidence_bars_html(
                    [
                        ("Evidence coverage", confidence.evidence_coverage),
                        ("Source freshness", confidence.source_freshness),
                        ("Specialist agreement", confidence.specialist_agreement),
                        ("Data quality", confidence.data_quality),
                        ("Conflict penalty", confidence.conflict_penalty),
                    ]
                ),
                unsafe_allow_html=True,
            )
        analytics = result.analytics
        if analytics is None:
            return
        st.caption("Claims performance")
        _render_time_series(
            [item.period for item in analytics.claims.loss_ratio.monthly],
            {"Loss ratio (%)": [item.value * 100 for item in analytics.claims.loss_ratio.monthly]},
            y_label="Loss ratio (%)",
        )
        st.caption("Claim severity")
        _render_time_series(
            [item.period for item in analytics.claims.average_severity_gbp.monthly],
            {
                "Average severity (GBP)": [
                    item.value for item in analytics.claims.average_severity_gbp.monthly
                ]
            },
            y_label="GBP per claim",
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
        st.caption("Competitor price movement")
        _render_time_series(
            (
                [item.period for item in analytics.competitors.competitors[0].price_index.monthly]
                if analytics.competitors.competitors
                else []
            ),
            {
                competitor.competitor_name: [item.value for item in competitor.price_index.monthly]
                for competitor in analytics.competitors.competitors
            },
            y_label="Price index",
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
    if response.elapsed_ms is not None:
        st.caption(_operation_summary(response))
    if response.activities or response.plan_details:
        with st.expander("Plan, decisions, and tool calls", expanded=False):
            if response.plan_details:
                st.markdown("**Plan**")
                st.write("\n".join(f"- {item}" for item in response.plan_details))
            if response.activities:
                st.markdown("**Tool activity and timing**")
                compact_activities = _compact_activities(response.activities)
                st.write("\n".join(f"- {_activity_text(item)}" for item in compact_activities))
    if response.tables:
        with st.expander("Supporting data details", expanded=False):
            for table in response.tables:
                _render_table(table)
    if response.workflow_result is not None:
        _render_workflow_result(response.workflow_result)
        if can_record and _can_record_decision(response.workflow_result):
            _render_decision_controls(response.workflow_result, message_number)


def _can_record_decision(result: WorkflowResult) -> bool:
    return result.analytics is not None and result.recommendation.action.value in {
        "increase",
        "decrease",
        "hold",
    }


def _render_clarification_suggestions(response: ChatResponse, message_number: int) -> None:
    if not response.requires_clarification:
        return
    placeholder = st.empty()
    with placeholder.container():
        for suggestion in response.suggested_next_steps:
            if st.button(suggestion, key=f"chat_suggestion_{message_number}_{suggestion}"):
                placeholder.empty()
                st.session_state.pending_chat_prompt = suggestion
                st.rerun()


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
                    status_class = "pc-monitoring-status-error"
                elif alert.insufficient_sample:
                    status = "🟡 insufficient sample"
                    status_class = "pc-monitoring-status-warn"
                else:
                    status = "🟢 normal"
                    status_class = "pc-monitoring-status-ok"
                st.markdown(
                    f'**{alert.metric_name}** - <span class="{status_class}">{status}</span>',
                    unsafe_allow_html=True,
                )
                st.caption(f"Baseline: {alert.baseline_window} | Current: {alert.current_window}")
                st.write(alert.detail)
                for measurement in alert.measurements:
                    st.caption(
                        f"{measurement.measure_kind.value}: {measurement.value:g} "
                        f"{measurement.unit} (threshold {measurement.threshold:g}, "
                        f"{'breached' if measurement.breached else 'within range'})"
                    )


def _activity_text(activity: ChatActivity) -> str:
    duration = _format_duration(activity.duration_ms)
    if activity.agent == "conversation-agent":
        if activity.status is ActivityStatus.WORKING:
            return "Thinking and processing the request."
        if activity.status is ActivityStatus.COMPLETED:
            return (
                f"Thought for {duration}. The plan is ready; next, call the selected tools and "
                "agents."
            )
    tool_name = _tool_name(activity.source, activity.label)
    agent_name = _agent_name(activity.agent)
    if activity.status is ActivityStatus.WORKING:
        if activity.source == "portfolio_analysis":
            return "Running the portfolio analysis workflow to combine the requested evidence."
        if activity.source == "recommendation":
            return "Calling the recommendation agent to create a pricing recommendation."
        if activity.source == "governance":
            return "Calling the governance agent to review the recommendation."
        if agent_name is not None:
            return f"Calling the {agent_name} to retrieve data."
        return f"Calling the {tool_name} to get the data."
    if activity.status is ActivityStatus.COMPLETED:
        if activity.source == "portfolio_analysis":
            return (
                "Completed the portfolio analysis workflow: combined claims, conversion, "
                "competitor, pricing-history, market, and "
                "customer-feedback evidence."
            )
        if activity.source == "recommendation":
            return _completed_action(
                "Called the recommendation agent and created a pricing recommendation", activity
            )
        if activity.source == "governance":
            return _completed_action(
                "Called the governance agent and completed the review", activity
            )
        if agent_name is not None:
            return _completed_action(f"Called the {agent_name} and got the data", activity)
        if activity.duration_ms is None or activity.duration_ms < 100:
            return f"Called the {tool_name} and got the data."
        return f"Called the {tool_name} and got the data in {duration}."
    status = activity.status.value.title()
    duration_suffix = _format_duration(activity.duration_ms, prefix=" - ")
    return f"{status}: {activity.label}{duration_suffix}"


def _completed_action(action: str, activity: ChatActivity) -> str:
    if activity.duration_ms is None or activity.duration_ms < 100:
        return f"{action}."
    return f"{action} in {_format_duration(activity.duration_ms)}."


def _format_duration(duration_ms: float | None, *, prefix: str = "") -> str:
    if duration_ms is None:
        return "a moment" if not prefix else ""
    return f"{prefix}{duration_ms / 1_000:.1f} seconds"


def _tool_name(source: str | None, fallback: str) -> str:
    names = {
        "claims": "claims data tool",
        "conversion": "conversion data tool",
        "competitors": "competitor data tool",
        "pricing_history": "pricing history tool",
        "market_intelligence": "market intelligence tool",
        "customer_feedback": "customer feedback tool",
        "schema_catalogue": "data catalogue tool",
        "evaluation": "evaluation report tool",
        "drift": "monitoring tool",
        "replay": "replay tool",
        "portfolio_analysis": "portfolio analysis workflow",
        "recommendation": "recommendation workflow",
        "governance": "governance review",
    }
    return names.get(source or "", fallback)


def _agent_name(agent: str | None) -> str | None:
    names = {
        "claims-specialist": "claims specialist agent",
        "conversion-specialist": "conversion specialist agent",
        "market-intelligence-specialist": "market-intelligence specialist agent",
        "pricing-history-specialist": "pricing-history specialist agent",
    }
    return names.get(agent or "")


def _activity_key(activity: ChatActivity) -> str:
    return activity.source or activity.agent or activity.label


def _compact_activities(activities: Sequence[ChatActivity]) -> list[ChatActivity]:
    latest_by_key: dict[str, ChatActivity] = {}
    order: list[str] = []
    for activity in activities:
        key = _activity_key(activity)
        if key not in latest_by_key:
            order.append(key)
        latest_by_key[key] = activity
    return [latest_by_key[key] for key in order]


def _operation_summary(response: ChatResponse) -> str:
    activity_count = len(_compact_activities(response.activities))
    tools = list(
        dict.fromkeys(
            _tool_name(activity.source, activity.label)
            for activity in _compact_activities(response.activities)
            if activity.source is not None
        )
    )
    elapsed = _format_duration(response.elapsed_ms)
    if not tools:
        return f"Completed in {elapsed}. Operation size: {activity_count} step(s), no data tools."
    return (
        f"Completed in {elapsed}. Operation size: {activity_count} step(s), "
        f"{len(tools)} tool(s). Tools used: {', '.join(tools)}."
    )


st.set_page_config(
    page_title="Aviva Pricing Decision Copilot", layout="wide", initial_sidebar_state="collapsed"
)
st.markdown(INJECT_CSS, unsafe_allow_html=True)

_HEADER_PORTFOLIO = PortfolioQuestion(
    product=Product.PERSONAL_MOTOR,
    region=Region.NORTH_WEST,
    segment=Segment.RENEWAL,
    analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
)
_DEFAULT_CHAT_CONTEXT = ChatContext(
    product=_HEADER_PORTFOLIO.product,
    region=_HEADER_PORTFOLIO.region,
    segment=_HEADER_PORTFOLIO.segment,
    analysis_start_month=_HEADER_PORTFOLIO.analysis_period.start_month,
    analysis_end_month=_HEADER_PORTFOLIO.analysis_period.end_month,
)
st.markdown(
    f"""
    <div class="pc-header">
      <div class="pc-header-left">
        <div class="pc-logo">P</div>
        <div>
          <div class="pc-title">Aviva Pricing Decision Copilot</div>
          <div class="pc-subtitle">Decision support only — never executes a pricing change</div>
        </div>
      </div>
      <div class="pc-portfolio-pill">{portfolio_pill_text(_HEADER_PORTFOLIO)}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = [
        {
            "role": "assistant",
            "response": ChatResponse(
                intent=ChatIntent.HELP,
                context=_DEFAULT_CHAT_CONTEXT,
                message=(
                    "Ask me about claims, conversion, competitors, previous pricing actions, "
                    "market intelligence, or aggregate customer feedback. You can also ask for a "
                    "pricing recommendation or say ‘analyse everything’."
                ),
            ).model_dump(mode="json"),
        }
    ]

tab_chat, tab_monitoring = st.tabs(["Chat", "Monitoring"])


def _render_copilot_label() -> None:
    st.markdown('<div class="pc-copilot-label">Copilot</div>', unsafe_allow_html=True)


def _submit_prompt(prompt: str) -> None:
    active_context = _DEFAULT_CHAT_CONTEXT.model_copy()
    conversation_history: list[ConversationMessage] = []
    for saved_message in st.session_state.chat_messages:
        saved_response = ChatResponse.model_validate(saved_message["response"])
        conversation_history.append(
            conversation_history_message(saved_message["role"], saved_response.message)
        )
        if saved_message["role"] == "assistant":
            active_context = saved_response.context

    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.chat_messages.append(
        {
            "role": "user",
            "response": ChatResponse(
                intent=ChatIntent.HELP, context=_DEFAULT_CHAT_CONTEXT, message=prompt
            ).model_dump(mode="json"),
        }
    )
    with st.chat_message("assistant", avatar=assistant_avatar_data_uri()):
        _render_copilot_label()
        activity_box = st.empty()
        activity_states: dict[str, ChatActivity] = {}
        activity_order: list[str] = []

        def show_activity(activity: ChatActivity) -> None:
            key = _activity_key(activity)
            if key not in activity_states:
                activity_order.append(key)
            activity_states[key] = activity
            activity_box.markdown(
                "  \n".join(_activity_text(activity_states[key]) for key in activity_order)
            )

        request_started = monotonic()
        response = ChatService().submit(
            prompt,
            active_context,
            history=conversation_history,
            on_activity=show_activity,
        )
        response = response.model_copy(
            update={"elapsed_ms": (monotonic() - request_started) * 1_000}
        )
        activity_box.empty()
        if "Live analysis could not complete" in response.message:
            retry_number = len(st.session_state.chat_messages)
            if st.button("Try replay instead", key=f"replay_retry_{retry_number}"):
                retry_context = ChatContext(scenario=response.context.scenario, force_replay=True)
                request_started = monotonic()
                response = ChatService().submit(
                    prompt,
                    retry_context,
                    history=conversation_history,
                    on_activity=show_activity,
                )
                response = response.model_copy(
                    update={"elapsed_ms": (monotonic() - request_started) * 1_000}
                )
        message_number = len(st.session_state.chat_messages)
        _render_response(response, message_number, can_record=True)
        _render_clarification_suggestions(response, message_number)
    st.session_state.chat_messages.append(
        {"role": "assistant", "response": response.model_dump(mode="json")}
    )


_SUGGESTIONS = [
    "Show claims and conversion performance",
    "What did competitors do this period?",
    "Analyse everything and recommend a pricing action",
]

with tab_chat:
    clicked_suggestion: str | None = None
    pending_prompt = st.session_state.pop("pending_chat_prompt", None)
    if len(st.session_state.chat_messages) == 1:
        empty_state = st.empty()
        with empty_state.container():
            st.markdown(
                """
            <div class="pc-empty-state">
              <div class="pc-empty-icon">P</div>
              <div class="pc-empty-heading">What would you like to review?</div>
              <div class="pc-empty-subtitle">Ask about claims, conversion, competitors, pricing
              history, or request a recommendation for this portfolio.</div>
            </div>
            """,
                unsafe_allow_html=True,
            )
            st.markdown('<div class="pc-suggestions">', unsafe_allow_html=True)
            chip_columns = st.columns(len(_SUGGESTIONS))
            for column, suggestion in zip(chip_columns, _SUGGESTIONS, strict=True):
                if column.button(suggestion, key=f"suggestion_{suggestion}"):
                    clicked_suggestion = suggestion
            st.markdown("</div>", unsafe_allow_html=True)
        if clicked_suggestion is not None:
            empty_state.empty()

    for message_number, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(
            message["role"],
            avatar=assistant_avatar_data_uri() if message["role"] == "assistant" else None,
        ):
            if message["role"] == "assistant":
                _render_copilot_label()
            response = ChatResponse.model_validate(message["response"])
            is_latest_message = message_number == len(st.session_state.chat_messages) - 1
            _render_response(response, message_number, can_record=is_latest_message)
            if is_latest_message and pending_prompt is None:
                _render_clarification_suggestions(response, message_number)

    submitted_prompt = pending_prompt
    if submitted_prompt is None:
        with st.bottom:
            prompt = st.chat_input(
                "Ask a portfolio-level pricing question",
                key="pricing_chat_input",
                max_chars=1_000,
                submit_mode="disable",
            )
        submitted_prompt = clicked_suggestion or prompt
    if submitted_prompt:
        _submit_prompt(submitted_prompt)
        st.html(AUTO_SCROLL_SCRIPT, unsafe_allow_javascript=True)
        if pending_prompt is not None:
            st.rerun()

with tab_monitoring:
    _render_drift_monitoring_tab()
