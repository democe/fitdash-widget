#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$project_dir"
uv run --locked ruff check backend tests
uv run --locked pytest -q
if [[ -n "${LUAU:-}" ]] || command -v luau >/dev/null 2>&1; then
  uv run --locked python tests/check_luau.py
else
  printf "%s\n" "Luau not found; set LUAU to run native Luau behavior tests."
fi
