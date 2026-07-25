from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.config import get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
    WorkflowResult,
)
from pricing_copilot.data.persistent import build_analytics_database
from pricing_copilot.recommendation.trace import save_baseline_trace
from pricing_copilot.replay.store import ReplayArtifactIncompatibleError, ReplayArtifactMissingError
from pricing_copilot.workflow import run_portfolio_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricing-copilot",
        description="Submit a portfolio pricing question to the governed workflow.",
    )
    parser.add_argument(
        "--build-data", action="store_true", help="Build the versioned synthetic DuckDB."
    )
    parser.add_argument("--product", choices=[p.value for p in Product])
    parser.add_argument("--region", choices=[r.value for r in Region])
    parser.add_argument("--segment", choices=[s.value for s in Segment])
    parser.add_argument("--start-month", help="YYYY-MM-DD")
    parser.add_argument("--end-month", help="YYYY-MM-DD")
    parser.add_argument(
        "--scenario", required=False, choices=[s.value for s in ScenarioName], default=None
    )
    parser.add_argument(
        "--save-trace",
        required=False,
        default=None,
        help="Optional path to save the validated result as a JSON trace for later benchmarking.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Serve a recorded replay artifact instead of a live analysis.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full result as stable JSON instead of a readable summary.",
    )
    parser.add_argument(
        "--record-replay-artifacts",
        action="store_true",
        help="Run all three supported scenarios live and save their replay artifacts.",
    )
    return parser


def _print_summary(result: WorkflowResult) -> None:
    recommendation = result.recommendation
    print(f"Source: {result.source.value}")
    print(f"Recommendation: {recommendation.action.value}")
    if recommendation.price_range is not None:
        print(
            f"  Range: {recommendation.price_range.lower_pct:g}% to "
            f"{recommendation.price_range.upper_pct:g}%"
        )
    print(f"Rationale: {recommendation.rationale}")
    if result.missing_evidence:
        print("Missing evidence:")
        for item in result.missing_evidence:
            print(f"  - {item.domain.value}: {item.reason}")
    print("Specialist reports:")
    for report in result.specialist_reports:
        print(f"  - {report.domain.value} ({report.status}): {report.summary}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.build_data:
        path = build_analytics_database(get_settings().analytics_database_path)
        print(path)
        return 0

    if args.record_replay_artifacts:
        from pricing_copilot.chat.contracts import ChatContext
        from pricing_copilot.chat.service import ChatService
        from pricing_copilot.replay.store import save_replay_artifact

        service = ChatService()
        for scenario in ScenarioName:
            response = service.submit("Recommend a pricing action", ChatContext(scenario=scenario))
            if response.workflow_result is None:
                print(f"Skipped {scenario.value}: no workflow_result in response.", file=sys.stderr)
                continue
            save_replay_artifact(response, get_settings())
            print(f"Recorded replay artifact for {scenario.value}.")
        return 0

    required_arguments = ("product", "region", "segment", "start_month", "end_month")
    missing = [
        f"--{name.replace('_', '-')}" for name in required_arguments if not getattr(args, name)
    ]
    if missing:
        parser.error(
            "the following arguments are required unless --build-data is used: "
            f"{', '.join(missing)}"
        )

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
        result = run_portfolio_workflow(question, replay=args.replay)
    except UnsupportedPortfolioError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
        print(f"Replay unavailable: {exc}", file=sys.stderr)
        return 1

    if args.save_trace:
        save_baseline_trace(result, Path(args.save_trace))

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
