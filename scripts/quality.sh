#!/usr/bin/env bash
set -euo pipefail

echo "==> Environment"
# A non-editable install avoids macOS hidden-file flags causing Python to skip the editable
# .pth file inside a hidden .venv directory. Reinstalling guarantees that the checks exercise
# the exact source tree from this run.
uv sync --all-groups --no-editable --reinstall-package pricing-copilot

echo "==> Ruff"
uv run --no-sync ruff check .

echo "==> MyPy"
uv run --no-sync mypy

echo "==> Pytest"
uv run --no-sync pytest

echo "==> Bandit"
uv run --no-sync bandit -q -r src

echo "==> Secret scan"
uv run --no-sync python scripts/check_secrets.py

echo "All quality checks passed."
