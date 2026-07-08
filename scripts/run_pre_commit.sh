#!/usr/bin/env bash
# Run all pre-commit hooks over the whole repo. Extra args (e.g. a hook id) are
# forwarded to `pre-commit run`.
set -euo pipefail

cd "$(dirname "$0")/.."

# Keep the `uv run` inside the ty hook from pruning the out-of-band Airflow install.
export UV_NO_SYNC=1

exec .venv/bin/pre-commit run --all-files --config .pre-commit-config.yaml "$@"
