#!/usr/bin/env bash
# Local dev bootstrap: uv venv (dev group) + pre-commit hooks.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required — install from https://docs.astral.sh/uv/ then re-run." >&2
    exit 1
fi

echo "==> uv sync (dev group)"
if [ "${UPDATE_LOCK:-false}" = "true" ]; then
    uv lock --upgrade
    uv sync --group dev
else
    uv sync --frozen --group dev
fi

# Airflow is a runtime peer (host-provided), so it stays out of the lockfile.
# Install the `airflow` extra into the venv so the adapter/loader/api tests can
# import it. Quality tooling (ruff/ty) does not need it.
echo "==> installing the 'airflow' extra (peer, not locked)"
uv pip install "apache-airflow>=3.1,<4"

echo "==> installing pre-commit hooks (pre-commit + commit-msg)"
uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg

echo "==> done. Try: make pre-commit && make test"
