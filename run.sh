#!/usr/bin/env bash
# Launch the VLAN Migrator from the project-local virtualenv (macOS / Linux).
# Passes through any args, e.g.:  ./run.sh list-basic
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SRC/.venv"
if [ ! -x "$VENV/bin/vlan-migrator" ]; then
  echo "venv not found. Run:  bash install.sh --no-run" >&2
  exit 1
fi
exec "$VENV/bin/vlan-migrator" "$@"
