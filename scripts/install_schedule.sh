#!/bin/zsh
# Installs a macOS LaunchAgent that runs the tracker every 3 hours (at :07 past
# 0,3,6,...,21 local time). If the Mac is asleep, launchd runs it once on wake.
set -euo pipefail
DIR="${0:A:h:h}"
LABEL=local.roblox-trend-tracker
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Already installed ($PLIST). To change it: scripts/uninstall_schedule.sh, then run this again."
  exit 0
fi

PY="$(command -v python3)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Needs Python 3.11+; found $("$PY" --version)"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"
chmod +x "$DIR/scripts/run.sh"

{
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$DIR/scripts/run.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TRACKER_PYTHON</key><string>$PY</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StandardOutPath</key><string>$DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/launchd.err.log</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StartCalendarInterval</key>
  <array>
EOF
  for h in 0 3 6 9 12 15 18 21; do
    echo "    <dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>7</integer></dict>"
  done
  cat <<EOF
  </array>
</dict>
</plist>
EOF
} > "$PLIST"

plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $PLIST"
echo "Runs every 3 hours at :07. Log: $DIR/logs/run.log"
