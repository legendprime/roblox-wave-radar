#!/bin/zsh
# Removes the LaunchAgent. Refuses while a collection is running, so nothing is cut off;
# the plist goes to the Trash rather than being deleted.
set -euo pipefail
LABEL=local.roblox-trend-tracker
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -qE '^\s*pid = [0-9]+'; then
  echo "A collection is running right now. Try again in a few minutes."
  exit 1
fi
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL"
fi
if [[ -f "$PLIST" ]]; then
  mv "$PLIST" "$HOME/.Trash/$LABEL.plist.$(date +%Y%m%d%H%M%S)"
fi
echo "Schedule removed. Data and reports are untouched."
