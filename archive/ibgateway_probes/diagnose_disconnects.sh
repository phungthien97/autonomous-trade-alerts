#!/bin/bash
# Root-cause dump for IB Gateway / worker disconnects.
set -u
echo "=== NOW ==="
date -u
TZ=America/Toronto date
echo
echo "=== UNITS / PORT ==="
systemctl is-active xvfb ibgateway live-worker.timer gateway-health.timer || true
ss -ltn | grep -E '4002|4001' || echo "PORT_DOWN"
echo
echo "=== MEMORY / LOAD ==="
free -h
uptime
echo
echo "=== HEALTH LOG (tail) ==="
tail -n 40 /home/ubuntu/ibc/logs/gateway-health.log 2>/dev/null || true
echo
echo "=== IBC LOG FILES ==="
ls -lt /home/ubuntu/ibc/logs/ibc-*.txt 2>/dev/null | head -n 8
LATEST=$(ls -t /home/ubuntu/ibc/logs/ibc-*.txt 2>/dev/null | head -n 1)
echo "LATEST=${LATEST:-none}"
if [ -n "${LATEST:-}" ]; then
  echo
  echo "=== IBC KEY EVENTS (latest) ==="
  grep -nE 'Login has completed|Unrecognized|Password|AutoRestart|Exit Session|Shutdown|Second Factor|competing|another computer|different IP|Logged out|LOGGED_|Login attempt|API port|Connectivity|HMDS|session' "$LATEST" | tail -n 120 || true
fi
echo
echo "=== WORKER: first failures in last 48h ==="
journalctl -u live-worker.service --since "48 hours ago" --no-pager 2>/dev/null \
  | grep -E 'ibkr_connect_failed|price_source=ibkr|timed out|ConnectionRefused|alert_cooldown|Make sure API' \
  | head -n 80 || true
echo
echo "=== WORKER: last successful IB price pulls ==="
journalctl -u live-worker.service --since "48 hours ago" --no-pager 2>/dev/null \
  | grep 'price_source=ibkr_rth' | tail -n 30 || true
echo
echo "=== WORKER: last 30 lines ==="
journalctl -u live-worker.service -n 30 --no-pager 2>/dev/null || true
echo
echo "=== COOLDOWN FILE ==="
cat /opt/autonomous-trade-alerts/state_live/alert_cooldown.json 2>/dev/null || echo none
echo
echo "=== LIVE CONNECT PROBE ==="
cd /opt/autonomous-trade-alerts
# shellcheck disable=SC1091
. .venv/bin/activate
python3 - <<'PY'
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from ib_insync import IB
ib = IB()
try:
    ib.connect("127.0.0.1", 4002, clientId=77, timeout=8)
    print("connect_ok", ib.managedAccounts())
    try:
        vals = ib.accountValues()
        print("accountValues_n", len(vals))
    except Exception as exc:
        print("accountValues_err", type(exc).__name__, exc)
    ib.disconnect()
except Exception as exc:
    print("connect_fail", type(exc).__name__, exc)
PY
