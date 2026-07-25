import asyncio
import json
from datetime import date
from typing import Any

from agents import FunctionTool
from agents.tool_context import ToolContext

from pricing_copilot.analytics.contracts import (
    ClaimsMetrics,
    CompetitorMetrics,
    CompetitorMovement,
    ConversionMetrics,
    MonthlyValue,
    PricingHistoryComparison,
    WindowMetric,
)
from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.corpus import DocumentRecord, DocumentSentiment, SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument
from pricing_copilot.orchestration.tools import (
    build_claims_tool,
    build_competitor_tool,
    build_conversion_tool,
    build_market_documents_tool,
    build_pricing_history_tool,
)


async def _call(tool: FunctionTool) -> Any:
    ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id="1", tool_arguments="{}")
    return await tool.on_invoke_tool(ctx, "{}")


def _invoke(tool: FunctionTool) -> Any:
    result = asyncio.run(_call(tool))
    return json.loads(result)


def _window(baseline: float, current: float) -> WindowMetric:
    return WindowMetric(
        baseline=baseline,
        current=current,
        movement_pct=(current - baseline) / baseline * 100,
        monthly=[MonthlyValue(period=date(2025, 12, 1), value=current)],
    )


def test_claims_tool_returns_evidence_id_and_loss_ratio() -> None:
    metrics = ClaimsMetrics(
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 1),
        claim_frequency=_window(0.1, 0.11),
        average_severity_gbp=_window(1000.0, 1100.0),
        incurred_loss_gbp=_window(100000.0, 121000.0),
        loss_ratio=_window(0.71, 0.82),
    )
    payload = _invoke(build_claims_tool(metrics, "claims-x"))
    assert payload["evidence_id"] == "claims-x"
    assert payload["loss_ratio"]["current"] == 0.82
    assert payload["loss_ratio"]["baseline"] == 0.71


def test_conversion_tool_returns_evidence_id_and_retention() -> None:
    metrics = ConversionMetrics(
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 1),
        quote_to_sale_conversion=_window(0.30, 0.29),
        renewal_retention=_window(0.80, 0.72),
        average_quoted_premium_gbp=_window(500.0, 510.0),
        segment_comparison={"renewal": _window(0.30, 0.29)},
    )
    payload = _invoke(build_conversion_tool(metrics, "conversion-x"))
    assert payload["evidence_id"] == "conversion-x"
    assert payload["renewal_retention"]["current"] == 0.72
    assert payload["segment_comparison"]["renewal"]["baseline"] == 0.30


def test_competitor_tool_returns_evidence_id_and_competitor_names() -> None:
    metrics = CompetitorMetrics(
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 1),
        competitors=[
            CompetitorMovement(
                competitor_name="Fictional Insurer A",
                price_index=_window(100.0, 103.0),
                rank=_window(2.0, 1.0),
            )
        ],
    )
    payload = _invoke(build_competitor_tool(metrics, "competitors-x"))
    assert payload["evidence_id"] == "competitors-x"
    assert payload["competitors"][0]["competitor_name"] == "Fictional Insurer A"
    assert payload["competitors"][0]["price_index"]["current"] == 103.0


def test_pricing_history_tool_embeds_matching_evidence_ids() -> None:
    history = [
        PricingHistoryComparison(
            period=date(2025, 6, 1),
            price_change_pct=2.0,
            rationale="Pilot increase.",
            conversion_impact_pct=-1.0,
            loss_ratio_impact_pct=-3.0,
        )
    ]
    payload = _invoke(build_pricing_history_tool(history, ["pricing-history-2025-06-01"]))
    assert payload[0]["evidence_id"] == "pricing-history-2025-06-01"
    assert payload[0]["price_change_pct"] == 2.0


def test_market_documents_tool_returns_body_text_and_ids() -> None:
    document = RetrievedDocument(
        document=DocumentRecord(
            document_id="doc-1",
            source_type=SourceType.MARKET_REPORT,
            title="t",
            body="Competitors reduced pricing by four percent.",
            source_date=date(2025, 11, 1),
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.NORTH_WEST,
            sentiment=DocumentSentiment.AGAINST_INCREASE,
        ),
        score=1.0,
    )
    tool = build_market_documents_tool([document])
    assert tool.name == "get_market_intelligence_documents"
    payload = _invoke(tool)
    assert payload[0]["evidence_id"] == "doc-1"
    assert "four percent" in payload[0]["body"]
