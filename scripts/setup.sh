#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
backend_dir="${XDG_DATA_HOME:-$HOME/.local/share}/fitdash-widget/venv"
command -v uv >/dev/null || { echo 'Install uv, then rerun setup.' >&2; exit 1; }
UV_PROJECT_ENVIRONMENT="$backend_dir" uv sync --project "$project_dir" --locked --no-dev
printf 'Backend installed: %s/bin/fitdash\n' "$backend_dir"
