from datetime import date

from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.streamlit_theme import (
    INJECT_CSS,
    assistant_avatar_data_uri,
    badge_html,
    confidence_bars_html,
    portfolio_pill_text,
)


def test_inject_css_defines_the_reference_palette() -> None:
    assert "<style>" in INJECT_CSS
    assert "oklch(47% 0.085 235)" in INJECT_CSS  # primary blue
    assert "IBM Plex Sans" in INJECT_CSS
    assert "IBM Plex Mono" in INJECT_CSS


def test_portfolio_pill_text_formats_region_product_segment_and_dates() -> None:
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(
            start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)
        ),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    assert portfolio_pill_text(question) == "North West · Personal motor · Renewal · Jul–Dec 2025"


def test_assistant_avatar_data_uri_is_an_svg_data_uri() -> None:
    uri = assistant_avatar_data_uri()
    assert uri.startswith("data:image/svg+xml;base64,")


def test_confidence_bars_html_renders_one_bar_per_item() -> None:
    html = confidence_bars_html([("Evidence coverage", 0.88), ("Data quality", 0.91)])
    assert html.count("width:88%") == 1
    assert html.count("width:91%") == 1
    assert "Evidence coverage" in html and "Data quality" in html


def test_badge_html_includes_label_and_detail() -> None:
    html = badge_html("Increase", "2% to 3%")
    assert "Proposed: Increase" in html
    assert "2% to 3%" in html
