import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_secrets import find_secret_matches  # noqa: E402


def test_flags_an_aws_style_key(tmp_path: Path) -> None:
    suspect = tmp_path / "config.py"
    suspect.write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')  # nosecret
    matches = find_secret_matches([str(suspect)])
    assert matches


def test_clean_file_has_no_matches(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text('greeting = "hello world"\n')
    matches = find_secret_matches([str(clean)])
    assert matches == []


def test_allowlisted_line_is_not_flagged(tmp_path: Path) -> None:
    allowlisted = tmp_path / "fixture.py"
    allowlisted.write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"  # nosecret\n')
    matches = find_secret_matches([str(allowlisted)])
    assert matches == []
