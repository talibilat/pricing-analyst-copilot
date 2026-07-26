from __future__ import annotations

import base64

from pricing_copilot.contracts import PortfolioQuestion

_REGION_LABELS = {"north_west": "North West", "south_east": "South East"}
_PRODUCT_LABELS = {"personal_motor": "Personal motor"}
_SEGMENT_LABELS = {"renewal": "Renewal", "new_business": "New business"}
_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def portfolio_pill_text(question: PortfolioQuestion) -> str:
    period = question.analysis_period
    start = _MONTH_ABBR[period.start_month.month]
    end = _MONTH_ABBR[period.end_month.month]
    if period.start_month.year == period.end_month.year:
        date_range = f"{start}–{end} {period.end_month.year}"
    else:
        date_range = (
            f"{start} {period.start_month.year}–{end} {period.end_month.year}"
        )
    return " · ".join(
        [
            _REGION_LABELS[question.region.value],
            _PRODUCT_LABELS[question.product.value],
            _SEGMENT_LABELS[question.segment.value],
            date_range,
        ]
    )


def assistant_avatar_data_uri() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44">'
        '<rect width="44" height="44" rx="12" fill="oklch(47% 0.085 235)"/>'
        '<text x="22" y="29" font-family="IBM Plex Sans, sans-serif" '
        'font-size="19" font-weight="600" fill="white" '
        'text-anchor="middle">P</text></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def confidence_bars_html(items: list[tuple[str, float]]) -> str:
    cells = []
    for label, fraction in items:
        pct = round(fraction * 100)
        cells.append(
            '<div class="pc-conf-cell">'
            f'<div class="pc-conf-label">{label}</div>'
            '<div class="pc-conf-track">'
            f'<div class="pc-conf-fill" style="width:{pct}%;"></div>'
            "</div>"
            f'<div class="pc-conf-value">{pct}%</div>'
            "</div>"
        )
    return f'<div class="pc-conf-grid">{"".join(cells)}</div>'


def badge_html(label: str, detail: str) -> str:
    return (
        '<div class="pc-workflow-badge-row">'
        f'<span class="pc-badge-action">Proposed: {label}</span>'
        f'<span class="pc-badge-detail">{detail}</span>'
        "</div>"
    )


INJECT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {
  background: oklch(98% 0.012 85);
  font-family: 'IBM Plex Sans', sans-serif;
  color: oklch(22% 0.015 85);
}
[data-testid="stHeader"] { background: transparent; }

.pc-header {
  display:flex; align-items:center; justify-content:space-between; gap:16px;
  padding:12px 4px 20px; border-bottom:1px solid oklch(89% 0.012 85);
}
.pc-header-left { display:flex; align-items:center; gap:12px; }
.pc-logo {
  width:32px; height:32px; border-radius:9px; background:oklch(47% 0.085 235);
  color:white; display:flex; align-items:center; justify-content:center;
  font-weight:600; font-size:15px; flex-shrink:0;
}
.pc-title { font-size:15px; font-weight:600; line-height:1.25; }
.pc-subtitle { font-size:12px; color:oklch(46% 0.014 85); }
.pc-portfolio-pill {
  font-size:12px; font-weight:500; color:oklch(38% 0.02 85);
  background:oklch(94% 0.012 85); border:1px solid oklch(89% 0.012 85);
  border-radius:999px; padding:6px 14px; white-space:nowrap;
}

.pc-empty-state {
  display:flex; flex-direction:column; align-items:center; text-align:center;
  gap:18px; padding-top:8vh;
}
.pc-empty-icon {
  width:44px; height:44px; border-radius:12px; background:oklch(47% 0.085 235);
  color:white; display:flex; align-items:center; justify-content:center;
  font-weight:600; font-size:19px;
}
.pc-empty-heading { font-size:20px; font-weight:600; }
.pc-empty-subtitle {
  font-size:14px; color:oklch(46% 0.014 85); max-width:440px; line-height:1.5;
}
.pc-suggestions .stButton button {
  font-size:13.5px; color:oklch(30% 0.02 85); background:white;
  border:1px solid oklch(88% 0.012 85); border-radius:10px; padding:10px 16px;
  text-align:left; box-shadow:none;
}
.pc-suggestions .stButton button:hover {
  border-color:oklch(47% 0.085 235); color:oklch(38% 0.09 235);
}

[data-testid="stChatMessage"] { gap:9px; }
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {
  border-radius:6px;
}

.pc-copilot-label {
  font-size:11.5px; font-weight:600; letter-spacing:0.04em; text-transform:uppercase;
  color:oklch(50% 0.014 85); margin-bottom:6px;
}

.pc-activity-trace {
  display:flex; flex-direction:column; gap:5px; background:oklch(96% 0.006 85);
  border:1px solid oklch(91% 0.008 85); border-radius:10px; padding:10px 14px;
  font-family:'IBM Plex Mono', monospace; font-size:12px; color:oklch(42% 0.02 85);
}

[data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; }

.pc-workflow-card {
  border:1px solid oklch(89% 0.012 85); border-radius:14px; background:white;
  padding:20px 22px; display:flex; flex-direction:column; gap:16px;
}
.pc-workflow-badge-row { display:flex; align-items:center; gap:10px; }
.pc-badge-action {
  font-size:11.5px; font-weight:700; letter-spacing:0.03em; text-transform:uppercase;
  color:oklch(52% 0.13 150); background:oklch(93% 0.05 150); border-radius:999px;
  padding:5px 12px;
}
.pc-badge-detail { font-size:13.5px; color:oklch(46% 0.014 85); }

.pc-conf-grid { display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; }
.pc-conf-cell { display:flex; flex-direction:column; gap:5px; }
.pc-conf-label { font-size:10.5px; color:oklch(50% 0.014 85); line-height:1.25; height:26px; }
.pc-conf-track { height:5px; border-radius:3px; background:oklch(92% 0.01 85); overflow:hidden; }
.pc-conf-fill { height:100%; border-radius:3px; background:oklch(47% 0.085 235); }
.pc-conf-value { font-size:12px; font-weight:600; }

[data-testid="stExpander"] {
  border:1px solid oklch(89% 0.012 85); border-radius:14px; background:white;
}

[data-testid="stChatInput"] textarea {
  font-family:'IBM Plex Sans', sans-serif; font-size:14.5px;
}
[data-testid="stChatInput"] {
  border-radius:16px !important; border:1px solid oklch(87% 0.012 85) !important;
}

[data-testid="stMetric"] { background:transparent; }
</style>
"""
