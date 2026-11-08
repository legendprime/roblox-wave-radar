#!/bin/zsh
# What the schedule runs: one collection + report, appended to logs/run.log.
set -u
DIR="${0:A:h:h}"
cd "$DIR" || exit 1
mkdir -p logs
LOG=logs/run.log
# Keep the log small: once it passes ~5 MB, the previous copy becomes run.log.1.
if [[ -f $LOG ]] && (( $(stat -f%z "$LOG") > 5000000 )); then
  mv -f "$LOG" "$LOG.1"
fi
PY="${TRACKER_PYTHON:-python3}"
"$PY" -m tracker run >> "$LOG" 2>&1
