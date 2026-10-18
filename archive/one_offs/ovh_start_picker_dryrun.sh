#!/bin/bash
# Install fixed timer + start a forced dry-run in background (full S&P; long).
set -euo pipefail
APP=/opt/autonomous-trade-alerts
cd "$APP"

sudo cp deploy/ibgateway/picker-rank.service /etc/systemd/system/
sudo cp deploy/ibgateway/picker-rank.timer /etc/systemd/system/
sudo sed -i 's/\r$//' /etc/systemd/system/picker-rank.service /etc/systemd/system/picker-rank.timer
sudo systemctl daemon-reload
sudo systemctl enable picker-rank.timer
sudo systemctl restart picker-rank.timer
systemctl is-active picker-rank.timer
systemctl list-timers picker-rank.timer --no-pager || true

mkdir -p state_picker/ranking_runs logs
# shellcheck disable=SC1091
. .venv/bin/activate
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

LOG="$APP/logs/picker_dryrun_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "starting dry-run log=$LOG"
nohup python -m app.picker_rank --dry-run --no-email --force >"$LOG" 2>&1 &
echo $! >"$APP/logs/picker_dryrun.pid"
echo "pid=$(cat "$APP/logs/picker_dryrun.pid")"
sleep 3
head -30 "$LOG" || true
