#!/bin/bash
set -euo pipefail
echo "===NOW==="
date -u
TZ=America/Toronto date
echo "===GATEWAY==="
systemctl is-active xvfb ibgateway || true
ss -ltn | grep 4002 || echo NO_4002
pgrep -c java || echo 0_java
echo "===HEALTH_LOG==="
tail -n 20 /home/ubuntu/ibc/logs/gateway-health.log 2>/dev/null || echo no_health_log
echo "===WORKER_TODAY_ET==="
# America/Toronto Oct 7 2026 starts ~2026-10-07 04:00 UTC (EDT)
journalctl -u live-worker.service --since "2026-10-07 04:00:00" --no-pager 2>/dev/null | tail -n 40 || true
echo "===COUNTS_SINCE_04UTC==="
echo -n "success_lines "
journalctl -u live-worker.service --since "2026-10-07 04:00:00" --no-pager 2>/dev/null | grep -c "actions" || true
echo -n "fail_lines "
journalctl -u live-worker.service --since "2026-10-07 04:00:00" --no-pager 2>/dev/null | grep -cE "Failed|ConnectionRefused|Traceback|ibkr_connect_failed" || true
echo "===IBGATEWAY_JOURNAL==="
journalctl -u ibgateway.service --since "2026-10-07 00:00:00" --no-pager 2>/dev/null | grep -E "Login has completed|Exit Session|Shutdown|AutoRestart|error|Error|Started|Stopped" | tail -n 40 || true
echo "===STATE==="
python3 <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone
p = Path("/opt/autonomous-trade-alerts/state_live")
for name in ["state.json", "equity.csv", "config.json"]:
    f = p / name
    if f.exists():
        print(name, "mtime_utc", datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat())
s = json.loads((p / "state.json").read_text())
print("cash", s.get("cash_usd"))
for sym, row in (s.get("assets") or {}).items():
    print(sym, {k: row.get(k) for k in ("shares", "last_price", "peak", "trough")})
eq = p / "equity.csv"
if eq.exists():
    lines = eq.read_text().strip().splitlines()
    print("equity_rows", max(0, len(lines) - 1))
    print("last5:")
    for line in lines[-5:]:
        print(line)
PY
echo "===TIMERS==="
systemctl list-timers live-worker.timer gateway-health.timer --no-pager || true
