#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
"$project_dir/scripts/setup.sh"
plugin_dir="${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins/fitdash"
mkdir -p -- "$(dirname -- "$plugin_dir")"
if [[ -e "$plugin_dir" || -L "$plugin_dir" ]]; then
  [[ "$(readlink -f -- "$plugin_dir")" == "$project_dir" ]] || { echo 'A different FitDash installation already exists.' >&2; exit 1; }
else
  ln -s -- "$project_dir" "$plugin_dir"
fi
noctalia msg config-reload
noctalia msg plugins enable shawn/fitdash
printf '%s\n' 'FitDash enabled. Add shawn/fitdash:steps to a bar using Noctalia settings.'
