#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
plugin_dir="${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins/fitdash"
backend_dir="${XDG_DATA_HOME:-$HOME/.local/share}/fitdash-widget"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/fitdash-widget"

if command -v noctalia >/dev/null 2>&1; then
  noctalia msg plugins disable democe/fitdash 2>/dev/null || true
  noctalia msg config-reload 2>/dev/null || true
fi

if [[ -L "$plugin_dir" || -e "$plugin_dir" ]]; then
  if [[ "$(readlink -f -- "$plugin_dir")" == "$project_dir" ]]; then
    rm -f -- "$plugin_dir"
    printf 'Removed plugin symlink: %s\n' "$plugin_dir"
  fi
fi

if [[ -d "$backend_dir" ]]; then
  rm -rf -- "$backend_dir"
  printf 'Removed backend directory: %s\n' "$backend_dir"
fi

purge=false
if [[ "${1:-}" == "--purge" || "${1:-}" == "-y" ]]; then
  purge=true
elif [[ -t 0 && -d "$state_dir" ]]; then
  read -r -p "Remove cached health data and state in $state_dir? [y/N] " answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    purge=true
  fi
fi

if [[ "$purge" == true && -d "$state_dir" ]]; then
  rm -rf -- "$state_dir"
  printf 'Removed state directory: %s\n' "$state_dir"
fi

printf '%s\n' 'FitDash uninstalled successfully.'
