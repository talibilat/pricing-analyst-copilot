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
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run the golden evaluation benchmark on both architectures and save the report.",
    )
    parser.add_argument(
        "--monitor-drift",
        action="store_true",
        help="Run drift monitoring against the latest evaluation report and save a drift report.",
    )
    parser.add_argument(
        "--check-promotion",
        action="store_true",
        help="Check the latest evaluation report against its targets and promote it if it passes.",
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

    if args.evaluate:
        from pricing_copilot.evaluation.runner import run_benchmark
        from pricing_copilot.evaluation.store import save_benchmark_report

        report = run_benchmark(get_settings())
        path = save_benchmark_report(report, get_settings())
        print(
            f"Golden set: {report.golden_set_version} "
            f"({len(report.governed.case_results)} governed cases)"
        )
        print(
            f"Governed: {report.governed.actuals.cases_passed} passed, "
            f"{report.governed.actuals.cases_failed} failed, "
            f"{report.governed.actuals.cases_errored} errored"
        )
        if report.baseline is not None:
            print(
                f"Baseline: {report.baseline.actuals.cases_passed} passed, "
                f"{report.baseline.actuals.cases_failed} failed, "
                f"{report.baseline.actuals.cases_errored} errored"
            )
        print(f"Saved to {path}")
        return 0

    if args.monitor_drift:
        from pricing_copilot.drift.monitor import run_drift_monitoring
        from pricing_copilot.drift.store import save_drift_report
        from pricing_copilot.evaluation.store import load_benchmark_report

        benchmark_report = load_benchmark_report(get_settings())
        if benchmark_report is None:
            print("No evaluation report is recorded yet. Run --evaluate first.", file=sys.stderr)
            return 1
        drift_report = run_drift_monitoring(get_settings(), benchmark_report)
        path = save_drift_report(drift_report, get_settings())
        material = drift_report.material_alerts
        print(f"Drift report: {len(drift_report.alerts)} alert(s), {len(material)} material.")
        for alert in material:
            print(f"  - {alert.category.value}/{alert.metric_name}: {alert.detail}")
        print(f"Saved to {path}")
        return 0

    if args.check_promotion:
        from pricing_copilot.evaluation.gate import evaluate_promotion_gate
        from pricing_copilot.evaluation.store import load_benchmark_report, save_promoted_report

        benchmark_report = load_benchmark_report(get_settings())
        if benchmark_report is None:
            print("No evaluation report is recorded yet. Run --evaluate first.", file=sys.stderr)
            return 1
        result = evaluate_promotion_gate(benchmark_report)
        if result.promoted:
            path = save_promoted_report(benchmark_report, get_settings())
            print(f"Promoted: {result.detail} Saved to {path}")
            return 0
        print(f"Not promoted: {result.detail}", file=sys.stderr)
        for metric in result.failing_metrics:
            print(f"  - failing metric: {metric}", file=sys.stderr)
        for case_id in result.failing_case_ids:
            print(f"  - failing case: {case_id}", file=sys.stderr)
        return 1

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
