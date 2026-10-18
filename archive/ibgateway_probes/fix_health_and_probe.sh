#!/bin/bash
# Strip CRLF from health scripts, install, deepen API probe, restart Gateway if zombie.
set -euo pipefail

APP=/opt/autonomous-trade-alerts
SRC_HEALTH="$APP/deploy/ibgateway/gateway-health.sh"
DST_HEALTH=/home/ubuntu/ibc/gateway-health.sh

# Prefer freshly uploaded source if present
if [ -f /tmp/gateway-health.sh ]; then
  SRC_HEALTH=/tmp/gateway-health.sh
fi

sed -i 's/\r$//' "$SRC_HEALTH" 2>/dev/null || true
sudo cp "$SRC_HEALTH" "$DST_HEALTH"
sudo sed -i 's/\r$//' "$DST_HEALTH"
sudo chmod +x "$DST_HEALTH"
sudo chown ubuntu:ubuntu "$DST_HEALTH"
file "$DST_HEALTH"

# Also fix common helper scripts that break under CRLF
for f in /home/ubuntu/set_ib_paper_login.sh /home/ubuntu/set_email_alerts.sh; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f"
    chmod +x "$f"
  fi
done

echo "=== timeline (python) ==="
cd "$APP"
# shellcheck disable=SC1091
. .venv/bin/activate
python3 - <<'PY'
import subprocess, re
out = subprocess.check_output(
    ["journalctl", "-u", "live-worker.service", "--since", "2026-10-12", "--no-pager"],
    text=True,
    stderr=subprocess.DEVNULL,
)
last_ok = None
first_to = None
first_fail = None
for line in out.splitlines():
    if "price_source=ibkr_rth" in line:
        last_ok = line
    if first_to is None and "timed out" in line:
        first_to = line
    if first_fail is None and "ibkr_connect_failed" in line:
        first_fail = line
print("LAST_OK:", last_ok)
print("FIRST_TIMEOUT:", first_to)
print("FIRST_CONNECT_FAIL:", first_fail)
# count today
ok = sum(1 for l in out.splitlines() if "price_source=ibkr_rth" in l)
to = sum(1 for l in out.splitlines() if "timed out" in l)
print(f"counts today: ibkr_ok_lines={ok} timeout_lines={to}")
PY

echo "=== restarting zombie gateway ==="
sudo systemctl stop live-worker.timer || true
sudo systemctl restart ibgateway.service
echo "waiting 45s for login..."
sleep 45
ss -ltn | grep 4002 || echo PORT_STILL_DOWN

python3 - <<'PY'
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from ib_insync import IB
ib = IB()
try:
    ib.connect("127.0.0.1", 4002, clientId=78, timeout=15)
    print("API_OK accounts=", ib.managedAccounts())
    print("accountValues_n=", len(ib.accountValues()))
    ib.disconnect()
except Exception as exc:
    print("API_STILL_BAD", type(exc).__name__, exc)
PY

sudo systemctl start live-worker.timer
systemctl is-active live-worker.timer ibgateway
echo "=== one worker cycle ==="
cd "$APP" && . .venv/bin/activate && python -m app.live_worker --mode broker_paper --broker ibkr 2>&1 | tail -n 20
