"""Lightweight secret-scanning check with no third-party dependency."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "generic_api_key_assignment": re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9/+_-]{16,}['\"]"
    ),
    "private_key_block": re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
}

EXCLUDED_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".ico", ".svg"}
ALLOWLIST_MARKER = "nosecret"


def find_secret_matches(paths: list[str]) -> list[str]:
    matches: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix in EXCLUDED_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            for lineno, line in enumerate(text.splitlines(), start=1):
                if ALLOWLIST_MARKER in line:
                    continue
                if pattern.search(line):
                    matches.append(f"{path}:{lineno}: possible {name}")
    return matches


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    matches = find_secret_matches(_tracked_files())
    if matches:
        print("Potential secrets found:", file=sys.stderr)
        for match in matches:
            print(f"  {match}", file=sys.stderr)
        return 1
    print("No potential secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
