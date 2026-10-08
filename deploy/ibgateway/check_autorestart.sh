#!/bin/bash
set -euo pipefail
echo "===NOW==="
date -u
TZ=America/Toronto date
echo "===UNITS==="
systemctl is-active xvfb ibgateway || true
systemctl show ibgateway -p ActiveEnterTimestamp --value || true
echo "===PORT==="
ss -ltn | grep 4002 || echo NO_4002
echo "===HEALTH==="
tail -n 15 /home/ubuntu/ibc/logs/gateway-health.log 2>/dev/null || echo no_health_log
echo "===IBC_EVENTS==="
LOG=$(ls -t /home/ubuntu/ibc/logs/ibc-3.24.2_GATEWAY-1050_*.txt | head -1)
echo "LOG=$LOG"
grep -E 'AutoRestart|Exit Session|Shutdown|Login has completed|autorestart|Gateway finished|Finding autorestart|Paper Log In' "$LOG" | tail -n 50
echo "===JOURNAL_SINCE_2330UTC==="
journalctl -u ibgateway.service --since "2026-10-07 23:30:00" --no-pager 2>/dev/null | tail -n 60 || true
echo "===SMOKE==="
cd /opt/autonomous-trade-alerts
. .venv/bin/activate
python - <<'PY'
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from app.broker.ibkr import IbkrBroker
b = IbkrBroker()
print("accounts", b.ib.managedAccounts())
print("snapshot", b.get_account_snapshot())
b.ib.disconnect()
print("SMOKE_OK")
PY
