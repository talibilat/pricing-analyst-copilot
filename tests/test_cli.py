import json

import pytest

from pricing_copilot.cli import main


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
