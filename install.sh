#!/usr/bin/env bash
# One-line installer for the Nutanix VLAN Migrator (macOS / Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.sh | bash
#
# Installs the tool into an isolated virtualenv, adds a global `vlan-migrator`
# command to your PATH, and launches it immediately.
set -euo pipefail

REPO="${VLANMIG_REPO:-https://github.com/guranshdeol/nutanix-vlan-migrator.git}"
BRANCH="${VLANMIG_BRANCH:-main}"
HOME_DIR="${VLANMIG_HOME:-$HOME/.nutanix-vlan-migrator}"
BIN_DIR="${VLANMIG_BIN:-$HOME/.local/bin}"
VENV="$HOME_DIR/venv"
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

# ---- determine install source: local checkout or git ref ----------------
SRC=""
if [ -n "${BASH_SOURCE:-}" ]; then
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
  [ -f "$d/pyproject.toml" ] && SRC="$d"
fi
[ -z "$SRC" ] && [ -f "./pyproject.toml" ] && SRC="$(pwd)"

# ---- create the isolated venv -------------------------------------------
say "Creating virtualenv at $VENV"
mkdir -p "$HOME_DIR"
"$PYBIN" -m venv "$VENV"
VENV_PY="$VENV/bin/python"
"$VENV_PY" -m pip install --upgrade pip wheel >/dev/null

if [ -n "$SRC" ]; then
  say "Installing from local checkout: $SRC"
  "$VENV_PY" -m pip install "$SRC"
else
  command -v git >/dev/null 2>&1 || die "git is required to install from $REPO"
  say "Installing from $REPO@$BRANCH"
  "$VENV_PY" -m pip install "git+$REPO@$BRANCH"
fi

# ---- expose a global `vlan-migrator` command ----------------------------
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/vlan-migrator" "$BIN_DIR/vlan-migrator"
ln -sf "$VENV/bin/vlanmig" "$BIN_DIR/vlanmig"
say "Linked global command -> $BIN_DIR/vlan-migrator"

# ---- ensure BIN_DIR is on PATH (persist in shell rc) --------------------
add_path_line='export PATH="$HOME/.local/bin:$PATH"'
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;  # already on PATH for this session
  *)
    for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
      if [ -f "$rc" ] || [ "$rc" = "$HOME/.profile" ]; then
        if ! grep -qsF "$BIN_DIR" "$rc" 2>/dev/null; then
          printf '\n# Added by nutanix-vlan-migrator installer\n%s\n' "$add_path_line" >> "$rc"
          say "Added $BIN_DIR to PATH in $rc"
        fi
      fi
    done
    ;;
esac

say "Installed. Use it anywhere by typing:  vlan-migrator"

# ---- auto-launch, reconnecting to the terminal if piped -----------------
if [ "$RUN_AFTER" -eq 1 ]; then
  say "Launching vlan-migrator..."
  if [ -t 0 ]; then
    exec "$VENV/bin/vlan-migrator"
  elif { : < /dev/tty; } 2>/dev/null; then
    # Piped install (curl | bash): stdin is the script, so read from the TTY.
    exec "$VENV/bin/vlan-migrator" < /dev/tty
  else
    echo "Open a new terminal (or run: export PATH=\"$BIN_DIR:\$PATH\") then type: vlan-migrator"
  fi
fi
