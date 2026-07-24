#!/usr/bin/env bash
# One-line installer for the Nutanix VLAN Migrator (macOS / Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.sh | bash
#
# Self-bootstrapping: on a fresh machine it will install the prerequisites it
# needs (Python 3.8+ with venv/pip, and git), then install the tool into an
# isolated virtualenv, add a global `vlan-migrator` command to your PATH, and
# launch it.
set -euo pipefail

REPO="${VLANMIG_REPO:-https://github.com/guranshdeol/nutanix-vlan-migrator.git}"
BRANCH="${VLANMIG_BRANCH:-main}"
HOME_DIR="${VLANMIG_HOME:-$HOME/.nutanix-vlan-migrator}"
BIN_DIR="${VLANMIG_BIN:-$HOME/.local/bin}"
VENV="$HOME_DIR/venv"
RUN_AFTER=1
for a in "$@"; do [ "$a" = "--no-run" ] && RUN_AFTER=0; done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mNote:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# sudo helper: empty when root, else `sudo` if available
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

# Find a Python that is >=3.8 AND has working venv + pip (ensurepip).
find_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && \
       "$c" -c 'import sys, venv, ensurepip; raise SystemExit(0 if sys.version_info[:2] >= (3,8) else 1)' >/dev/null 2>&1; then
      printf '%s' "$c"; return 0
    fi
  done
  return 1
}

# Load Homebrew into PATH if it is installed anywhere standard.
_load_brew() {
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && eval "$("$p" shellenv)" && return 0
  done
  command -v brew >/dev/null 2>&1
}

ensure_python() {
  if find_python >/dev/null 2>&1; then return 0; fi
  say "Python 3.8+ (with venv/pip) not found - installing prerequisites..."
  case "$(uname -s)" in
    Darwin)
      if ! _load_brew; then
        say "Installing Homebrew (may prompt for your password)..."
        if [ -e /dev/tty ]; then
          NONINTERACTIVE=1 /bin/bash -c \
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty || true
        else
          NONINTERACTIVE=1 /bin/bash -c \
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || true
        fi
        _load_brew || true
      fi
      command -v brew >/dev/null 2>&1 && brew install python git || true
      ;;
    Linux)
      if   command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update -y && $SUDO apt-get install -y python3 python3-venv python3-pip git curl
      elif command -v dnf     >/dev/null 2>&1; then $SUDO dnf install -y python3 python3-pip git curl
      elif command -v yum     >/dev/null 2>&1; then $SUDO yum install -y python3 python3-pip git curl
      elif command -v pacman  >/dev/null 2>&1; then $SUDO pacman -Sy --noconfirm python git curl
      elif command -v zypper  >/dev/null 2>&1; then $SUDO zypper install -y python3 python3-venv python3-pip git curl
      elif command -v apk     >/dev/null 2>&1; then $SUDO apk add python3 py3-pip git curl
      else die "Could not detect a package manager. Please install Python 3.8+ and git manually, then re-run."
      fi
      ;;
    *) die "Unsupported OS. Please install Python 3.8+ and git manually, then re-run." ;;
  esac
  find_python >/dev/null 2>&1 || die "Python could not be installed automatically. Please install Python 3.8+ manually and re-run."
}

# Verify git is present; install it via the platform package manager if not.
ensure_git() {
  command -v git >/dev/null 2>&1 && return 0
  say "git not found - attempting to install it..."
  case "$(uname -s)" in
    Darwin)
      if _load_brew; then brew install git
      else xcode-select --install >/dev/null 2>&1 || true
           die "git is missing. macOS is opening the Command Line Tools installer - finish it, then re-run this command."
      fi
      ;;
    Linux)
      if   command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update -y && $SUDO apt-get install -y git
      elif command -v dnf     >/dev/null 2>&1; then $SUDO dnf install -y git
      elif command -v yum     >/dev/null 2>&1; then $SUDO yum install -y git
      elif command -v pacman  >/dev/null 2>&1; then $SUDO pacman -Sy --noconfirm git
      elif command -v zypper  >/dev/null 2>&1; then $SUDO zypper install -y git
      elif command -v apk     >/dev/null 2>&1; then $SUDO apk add git
      else die "Could not detect a package manager. Please install git manually and re-run."
      fi
      ;;
  esac
  command -v git >/dev/null 2>&1 || die "git installation did not succeed. Please install git manually and re-run."
  say "git installed: $(git --version)"
}

# ---- bootstrap prerequisites --------------------------------------------
ensure_python
PYBIN="$(find_python)" || die "Python 3.8+ is required but could not be prepared."
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
rm -rf "$VENV"
"$PYBIN" -m venv "$VENV"
VENV_PY="$VENV/bin/python"
"$VENV_PY" -m pip install --upgrade pip wheel >/dev/null

if [ -n "$SRC" ]; then
  say "Installing from local checkout: $SRC"
  "$VENV_PY" -m pip install "$SRC"
else
  ensure_git
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
  *":$BIN_DIR:"*) : ;;
  *)
    for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
      if [ -f "$rc" ] || [ "$rc" = "$HOME/.profile" ]; then
        if ! grep -qsF "$BIN_DIR" "$rc" 2>/dev/null; then
          printf '\n# Added by nutanix-vlan-migrator installer\n%s\n' "$add_path_line" >> "$rc"
          say "Added $BIN_DIR to PATH in $rc"
        fi
      fi
    done
    export PATH="$BIN_DIR:$PATH"
    ;;
esac

say "Installed. Use it anywhere by typing:  vlan-migrator"

# ---- auto-launch, reconnecting to the terminal if piped -----------------
if [ "$RUN_AFTER" -eq 1 ]; then
  say "Launching vlan-migrator..."
  if [ -t 0 ]; then
    exec "$VENV/bin/vlan-migrator"
  elif { : < /dev/tty; } 2>/dev/null; then
    exec "$VENV/bin/vlan-migrator" < /dev/tty
  else
    warn "Open a new terminal (or run: export PATH=\"$BIN_DIR:\$PATH\") then type: vlan-migrator"
  fi
fi
