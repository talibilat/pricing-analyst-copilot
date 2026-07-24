#!/usr/bin/env bash
set -euo pipefail

echo "==> Ruff"
uv run ruff check .

echo "==> MyPy"
uv run mypy

echo "==> Pytest"
uv run pytest

echo "==> Bandit"
uv run bandit -q -r src

echo "==> Secret scan"
uv run python scripts/check_secrets.py

echo "All quality checks passed."
