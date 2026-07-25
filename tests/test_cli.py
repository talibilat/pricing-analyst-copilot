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
