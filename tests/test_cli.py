import json
from pathlib import Path

import pytest

from pricing_copilot.cli import main


def test_cli_build_data_creates_a_duckdb_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "synthetic.duckdb"
    monkeypatch.setenv("PRICING_COPILOT_ANALYTICS_DATABASE_PATH", str(database_path))
    from pricing_copilot.config import get_settings

    get_settings.cache_clear()
    try:
        assert main(["--build-data"]) == 0
    finally:
        get_settings.cache_clear()
    assert Path(capsys.readouterr().out.strip()) == database_path
    assert database_path.exists()


def test_cli_prints_investigate_result_for_supported_portfolio(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "north_west",
            "--segment",
            "renewal",
            "--start-month",
            "2026-01-01",
            "--end-month",
            "2026-06-01",
            "--json",
        ]
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["recommendation"]["action"] == "investigate"


def test_cli_reports_clear_error_for_unsupported_region(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "south_east",
            "--segment",
            "renewal",
            "--start-month",
            "2026-01-01",
            "--end-month",
            "2026-06-01",
        ]
    )
    assert exit_code == 1
    assert "south_east" in capsys.readouterr().err


def test_cli_save_trace_flag_writes_a_file(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "north_west",
            "--segment",
            "renewal",
            "--start-month",
            "2026-01-01",
            "--end-month",
            "2026-06-01",
            "--save-trace",
            str(trace_path),
        ]
    )
    assert exit_code == 0
    assert trace_path.exists()


def test_cli_default_output_is_a_readable_summary_not_raw_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "north_west",
            "--segment",
            "renewal",
            "--start-month",
            "2026-01-01",
            "--end-month",
            "2026-06-01",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Recommendation:" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_cli_replay_flag_serves_a_recorded_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import date

    from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatResponse
    from pricing_copilot.config import Settings
    from pricing_copilot.contracts import (
        AnalysisPeriod,
        GovernanceOutcome,
        PortfolioQuestion,
        Product,
        Recommendation,
        RecommendationAction,
        Region,
        ScenarioName,
        Segment,
        WorkflowResult,
    )
    from pricing_copilot.replay.store import save_replay_artifact

    replay_dir = tmp_path / "replay"
    monkeypatch.setenv("PRICING_COPILOT_REPLAY_DIRECTORY", str(replay_dir))
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2025, 7, 1), end_month=date(2025, 12, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    save_replay_artifact(
        ChatResponse(
            intent=ChatIntent.PRICING_ANALYSIS,
            context=ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
            message="Recommends increase.",
            workflow_result=WorkflowResult(
                question=question,
                specialist_reports=[],
                recommendation=Recommendation(
                    action=RecommendationAction.INCREASE, rationale="Loss ratio rose."
                ),
                governance_outcome=GovernanceOutcome(approved=True),
                missing_evidence=[],
            ),
        ),
        Settings(replay_directory=replay_dir),
    )

    exit_code = main(
        [
            "--product",
            "personal_motor",
            "--region",
            "north_west",
            "--segment",
            "renewal",
            "--start-month",
            "2025-07-01",
            "--end-month",
            "2025-12-01",
            "--scenario",
            "controlled_increase",
            "--replay",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["source"] == "replay"
    assert payload["recommendation"]["action"] == "increase"


def test_cli_evaluate_flag_runs_the_deterministic_subset_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pricing_copilot.config import get_settings
    from pricing_copilot.evaluation import golden_set
    from pricing_copilot.evaluation.contracts import CaseKind

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    deterministic_only = [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC]
    monkeypatch.setattr("pricing_copilot.evaluation.runner.GOLDEN_CASES", deterministic_only)

    get_settings.cache_clear()
    try:
        exit_code = main(["--evaluate"])
    finally:
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Governed:" in out
    assert (tmp_path / "evaluation" / "latest.json").exists()


def test_cli_monitor_drift_flag_requires_an_evaluation_report_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pricing_copilot.config import get_settings

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    monkeypatch.setenv("PRICING_COPILOT_DRIFT_DIRECTORY", str(tmp_path / "drift"))
    get_settings.cache_clear()
    try:
        exit_code = main(["--monitor-drift"])
    finally:
        get_settings.cache_clear()
    assert exit_code == 1
    assert "no evaluation report" in capsys.readouterr().err.lower()


def test_cli_monitor_drift_flag_runs_after_an_evaluation_report_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pricing_copilot.config import get_settings
    from pricing_copilot.evaluation import golden_set
    from pricing_copilot.evaluation.contracts import CaseKind
    from pricing_copilot.evaluation.runner import run_benchmark
    from pricing_copilot.evaluation.store import save_benchmark_report

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    monkeypatch.setenv("PRICING_COPILOT_DRIFT_DIRECTORY", str(tmp_path / "drift"))
    monkeypatch.setattr(
        "pricing_copilot.evaluation.runner.GOLDEN_CASES",
        [c for c in golden_set.GOLDEN_CASES if c.kind == CaseKind.DETERMINISTIC],
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        save_benchmark_report(run_benchmark(settings, include_baseline=False), settings)
        exit_code = main(["--monitor-drift"])
    finally:
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "material" in out.lower()
    assert (tmp_path / "drift" / "latest.json").exists()


def test_cli_check_promotion_flag_promotes_a_passing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import UTC, datetime

    from pricing_copilot.config import Settings, get_settings
    from pricing_copilot.evaluation.contracts import (
        BenchmarkReport,
        EvaluationActuals,
        EvaluationReport,
        EvaluationTargets,
    )
    from pricing_copilot.evaluation.store import save_benchmark_report
    from pricing_copilot.versions import current_configuration_versions

    monkeypatch.setenv("PRICING_COPILOT_EVALUATION_DIRECTORY", str(tmp_path / "evaluation"))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        actuals = EvaluationActuals(
            deterministic_accuracy_pct=100.0,
            output_schema_valid_pct=100.0,
            citation_coverage_pct=100.0,
            ambiguous_abstention_pct=100.0,
            prompt_injection_success_pct=0.0,
            critical_guardrail_pass_pct=100.0,
            specialist_routing_accuracy_pct=100.0,
            unsupported_recommendation_count=0,
            latency_p95_seconds=10.0,
            tool_call_failure_pct=0.0,
            total_estimated_cost_gbp=0.0,
            total_tokens=0,
            governance_rejection_count=0,
            safe_abstention_count=0,
            cases_passed=10,
            cases_failed=0,
            cases_errored=0,
        )
        governed = EvaluationReport(
            architecture="governed",
            generated_at=datetime.now(UTC),
            targets=EvaluationTargets(),
            actuals=actuals,
            case_results=[],
        )
        report = BenchmarkReport(
            report_version="benchmark-report-v1",
            golden_set_version="golden-set-v1",
            generated_at=datetime.now(UTC),
            configuration_versions=current_configuration_versions(Settings()),
            governed=governed,
        )
        save_benchmark_report(report, settings)
        exit_code = main(["--check-promotion"])
    finally:
        get_settings.cache_clear()
    assert exit_code == 0
    assert "promoted" in capsys.readouterr().out.lower()
    assert (tmp_path / "evaluation" / "promoted.json").exists()
