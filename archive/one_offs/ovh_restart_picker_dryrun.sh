#!/bin/bash
set -euo pipefail
APP=/opt/autonomous-trade-alerts
cd "$APP"
# shellcheck disable=SC1091
. .venv/bin/activate
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
mkdir -p logs state_picker/ranking_runs
if [ -f logs/picker_dryrun.pid ]; then
  kill "$(cat logs/picker_dryrun.pid)" 2>/dev/null || true
fi
# Ensure live-worker still healthy after deploy
sudo systemctl start live-worker.timer 2>/dev/null || true
LOG="$APP/logs/picker_dryrun_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "starting dry-run log=$LOG"
nohup python -m app.picker_rank --dry-run --no-email --force >"$LOG" 2>&1 &
echo $! >"$APP/logs/picker_dryrun.pid"
echo "pid=$(cat logs/picker_dryrun.pid)"
sleep 5
head -40 "$LOG" || true
