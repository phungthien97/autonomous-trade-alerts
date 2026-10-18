#!/bin/bash
set -euo pipefail
APP=/opt/autonomous-trade-alerts
cd "$APP"

# Strip CRLF from shell units we deploy from Windows
find deploy/ibgateway -name '*.sh' -print0 | xargs -0 sed -i 's/\r$//'
sed -i 's/\r$//' deploy/ibgateway/picker-rank.service deploy/ibgateway/picker-rank.timer || true
sudo sed -i 's/\r$//' /etc/systemd/system/picker-rank.service /etc/systemd/system/picker-rank.timer || true
sudo systemctl daemon-reload
sudo systemctl restart picker-rank.timer
systemctl is-active picker-rank.timer

# Kill prior dry-run
if [ -f logs/picker_dryrun.pid ]; then
  kill "$(cat logs/picker_dryrun.pid)" 2>/dev/null || true
  rm -f logs/picker_dryrun.pid
fi
pkill -f 'python -m app.picker_rank' 2>/dev/null || true

# shellcheck disable=SC1091
. .venv/bin/activate
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
# Avoid clashing with live-worker clientId=1
export IB_CLIENT_ID="${PICKER_IB_CLIENT_ID:-7}"

mkdir -p logs state_picker/ranking_runs
LOG="$APP/logs/picker_dryrun_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "starting dry-run client_id=$IB_CLIENT_ID log=$LOG"
PYTHONUNBUFFERED=1 nohup python -m app.picker_rank --dry-run --no-email --force >"$LOG" 2>&1 &
echo $! >"$APP/logs/picker_dryrun.pid"
echo "pid=$(cat logs/picker_dryrun.pid)"
sleep 8
ps -p "$(cat logs/picker_dryrun.pid)" -o pid,etime,cmd --no-headers || echo "process_exited"
echo "--- log ---"
wc -l "$LOG"
tail -40 "$LOG" || true
echo "--- status (first 25) ---"
bash deploy/ibgateway/status.sh 2>&1 | head -25
