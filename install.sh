#!/usr/bin/env bash
# One-line installer for the Nutanix VLAN Migrator (macOS / Linux).
#
#   Remote (recommended):
#     curl -fsSL https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.sh | bash
#
#   From a local checkout:
#     bash install.sh
#
# Creates a self-contained virtualenv (.venv) inside the project, installs the
# tool + all dependencies into it, then launches it. Nothing is placed on your
# system PATH; everything lives in <project>/.venv.
set -euo pipefail

REPO="${VLANMIG_REPO:-https://github.com/guranshdeol/nutanix-vlan-migrator.git}"
BRANCH="${VLANMIG_BRANCH:-main}"
RUN_AFTER=1
for a in "$@"; do [ "$a" = "--no-run" ] && RUN_AFTER=0; done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- find a suitable Python (>=3.8) -------------------------------------
PYBIN=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && \
     "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,8) else 1)'; then
    PYBIN="$c"; break
  fi
done
[ -n "$PYBIN" ] || die "Python 3.8+ is required but was not found."
say "Using Python: $("$PYBIN" --version 2>&1)"

# ---- locate the source tree (local checkout) or clone it ----------------
SRC=""
if [ -n "${BASH_SOURCE:-}" ]; then
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
  [ -f "$d/pyproject.toml" ] && SRC="$d"
fi
[ -z "$SRC" ] && [ -f "./pyproject.toml" ] && SRC="$(pwd)"

if [ -z "$SRC" ]; then
  command -v git >/dev/null 2>&1 || die "git is required to clone $REPO"
  TARGET="${VLANMIG_DIR:-$(pwd)/nutanix-vlan-migrator}"
  if [ -d "$TARGET/.git" ]; then
    say "Updating existing checkout at $TARGET"
    git -C "$TARGET" pull --ff-only
  else
    say "Cloning $REPO -> $TARGET"
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$TARGET"
  fi
  SRC="$TARGET"
fi
say "Source: $SRC"

# ---- create the project-local venv --------------------------------------
VENV="$SRC/.venv"
say "Creating virtualenv at $VENV"
"$PYBIN" -m venv "$VENV"
VENV_PY="$VENV/bin/python"

say "Installing tool and dependencies into the venv..."
"$VENV_PY" -m pip install --upgrade pip wheel >/dev/null
"$VENV_PY" -m pip install "$SRC"

say "Installed into $VENV (isolated; not on system PATH)."
echo "Run it any time with:  (cd \"$SRC\" && ./run.sh)   or   \"$VENV/bin/vlan-migrator\""

if [ "$RUN_AFTER" -eq 1 ] && [ -t 0 ]; then
  say "Launching vlan-migrator..."
  exec "$VENV/bin/vlan-migrator"
elif [ "$RUN_AFTER" -eq 1 ]; then
  say "No TTY detected (piped install). Start it in your terminal:"
  echo "  \"$VENV/bin/vlan-migrator\""
fi
