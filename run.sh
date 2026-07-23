#!/usr/bin/env bash
# Convenience launcher (macOS / Linux). Prefers the global install, falls back
# to a local .venv. Passes through args, e.g.:  ./run.sh list-basic
set -euo pipefail
GLOBAL="$HOME/.nutanix-vlan-migrator/venv/bin/vlan-migrator"
LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.venv/bin/vlan-migrator"
if   [ -x "$GLOBAL" ]; then exec "$GLOBAL" "$@"
elif [ -x "$LOCAL"  ]; then exec "$LOCAL"  "$@"
else
  echo "Not installed yet. Run:  bash install.sh" >&2
  exit 1
fi
