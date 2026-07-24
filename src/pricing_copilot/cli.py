from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.recommendation.trace import save_baseline_trace
from pricing_copilot.workflow import run_portfolio_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricing-copilot",
        description="Submit a portfolio pricing question to the governed workflow.",
    )
    parser.add_argument("--product", required=True, choices=[p.value for p in Product])
    parser.add_argument("--region", required=True, choices=[r.value for r in Region])
    parser.add_argument("--segment", required=True, choices=[s.value for s in Segment])
    parser.add_argument("--start-month", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-month", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--scenario", required=False, choices=[s.value for s in ScenarioName], default=None
    )
    parser.add_argument(
        "--save-trace",
        required=False,
        default=None,
        help="Optional path to save the validated result as a JSON trace for later benchmarking.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        question = PortfolioQuestion(
            product=Product(args.product),
            region=Region(args.region),
            segment=Segment(args.segment),
            analysis_period=AnalysisPeriod(
                start_month=date.fromisoformat(args.start_month),
                end_month=date.fromisoformat(args.end_month),
            ),
            scenario=ScenarioName(args.scenario) if args.scenario else None,
        )
    except ValidationError as exc:
        print(f"Invalid portfolio question: {exc}", file=sys.stderr)
        return 1

    try:
        result = run_portfolio_workflow(question)
    except UnsupportedPortfolioError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.save_trace:
        save_baseline_trace(result, Path(args.save_trace))

    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
