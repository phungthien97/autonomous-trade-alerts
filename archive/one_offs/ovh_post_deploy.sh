#!/bin/bash
set -euo pipefail
cd /opt/autonomous-trade-alerts
# shellcheck disable=SC1091
. .venv/bin/activate
python - <<'PY'
from app.picker.run import run_ranking
from app.live_worker import run_live_once
from app.live.planner import plan_from_signal
print("imports_ok")
PY
test -f app/picker_rank.py
test -f deploy/ibgateway/picker-rank.service
test -f deploy/ibgateway/picker-rank.timer
grep -q buy_cash_cap app/live/planner.py
grep -q "config.total_cash" app/live_worker.py
echo "deploy_verify_ok lines=$(wc -l < app/live_worker.py)"

# Install picker timer (dry-run mode in unit file)
sudo cp deploy/ibgateway/picker-rank.service /etc/systemd/system/
sudo cp deploy/ibgateway/picker-rank.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now picker-rank.timer
systemctl is-enabled picker-rank.timer
systemctl list-timers picker-rank.timer --no-pager || true
echo "timer_installed"
