#!/bin/bash
# Installs downloads-organizer as a launchd agent. Safe to run again.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd -P)"
LABEL="com.user.downloads-organizer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/downloads-organizer"
DOMAIN="gui/$(id -u)"
MODEL="$(sed -n 's/^model *= *"\(.*\)".*/\1/p' config.toml)"
MODEL="${MODEL:-gemma3:12b}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

step() { printf '\n==> %s\n' "$1"; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

step "1/8 Checking macOS and Homebrew"
[ "$(uname -s)" = "Darwin" ] || die "this service only runs on macOS"
command -v brew >/dev/null || die "Homebrew not found. Install it from https://brew.sh"
echo "macOS $(sw_vers -productVersion), $(brew --version | head -1)"

step "2/8 Checking the tag tool"
if command -v tag >/dev/null; then
    echo "tag found at $(command -v tag)"
else
    brew install tag
fi

step "3/8 Creating .venv and installing requirements"
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null &&
        "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done
[ -n "$PYTHON" ] || die "Python 3.12 or newer not found (brew install python@3.13)"
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
echo "using $(.venv/bin/python --version) at $PROJECT_DIR/.venv"

step "4/8 Checking the model $MODEL"
command -v ollama >/dev/null || die "ollama not found. Install it from https://ollama.com"
if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$MODEL"; then
    echo "$MODEL is installed"
else
    ollama pull "$MODEL"
fi

step "5/8 Writing $PLIST"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
escape() { printf '%s' "$1" | sed -e 's/[&|\\]/\\&/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
sed -e "s|__PYTHON__|$(escape "$PROJECT_DIR/.venv/bin/python")|" \
    -e "s|__WORKDIR__|$(escape "$PROJECT_DIR")|" \
    -e "s|__LOGDIR__|$(escape "$LOG_DIR")|g" \
    "$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST"

step "6/8 Loading the launchd agent"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
# bootout is asynchronous; wait for the old instance to go away.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 1
done
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL"
echo "loaded $LABEL"

step "7/8 Installing the Finder Quick Action"
.venv/bin/python -m organizer finder-action install

step "8/8 Running doctor"
sleep 3
.venv/bin/python -m organizer doctor || true

REAL_PYTHON="$(.venv/bin/python -c 'import os, sys; print(os.path.realpath(sys.executable))')"
cat <<MSG

Next steps (they need you, not this script):
  1. Grant Full Disk Access to: $REAL_PYTHON
     (System Settings > Privacy & Security > Full Disk Access, see README.md)
  2. Then restart the service:  launchctl kickstart -k $DOMAIN/$LABEL
  3. Turn on "Launch at login" in the Ollama app settings.
MSG
