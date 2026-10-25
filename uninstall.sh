#!/bin/bash
# Stops the launchd agent and removes its plist. The state database and logs stay.
set -uo pipefail

LABEL="com.user.downloads-organizer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; then
    echo "stopped $LABEL"
else
    echo "$LABEL was not loaded"
fi
if [ -f "$PLIST" ]; then
    rm "$PLIST"
    echo "removed $PLIST"
fi
cd "$(dirname "$0")"
[ -x .venv/bin/python ] && .venv/bin/python -m organizer finder-action remove
echo "kept: ~/Library/Application Support/downloads-organizer (state.db, renames.jsonl)"
echo "kept: ~/Library/Logs/downloads-organizer"
