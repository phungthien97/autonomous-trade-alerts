#!/bin/bash
set -euo pipefail
APP=/opt/autonomous-trade-alerts
pid=$(cat "$APP/logs/picker_dryrun.pid")
echo "pid=$pid"
ps -p "$pid" -o pid,etime,pcpu,pmem,state,wchan:32,cmd --no-headers
echo "--- stack (py-spy if present, else /proc status) ---"
if command -v py-spy >/dev/null 2>&1; then
  sudo py-spy dump --pid "$pid" 2>/dev/null | head -40 || true
fi
tr '\0' ' ' < "/proc/$pid/cmdline"; echo
cat "/proc/$pid/status" | egrep 'State|Threads|voluntary'
echo "--- sample one historical call with client 8 ---"
cd "$APP"
# shellcheck disable=SC1091
. .venv/bin/activate
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
export IB_CLIENT_ID=8
PYTHONUNBUFFERED=1 timeout 90 python - <<'PY'
from datetime import date, timedelta
from app.broker.ibkr import IbkrBroker
b = IbkrBroker(dry_run=True)
end = date.today()
start = end - timedelta(days=40)
print("connected", b.ib.isConnected())
rows = b.historical_hourly_closes("AAPL", start=start, end=end, use_rth=True)
print("rows", len(rows), "first", rows[0] if rows else None, "last", rows[-1] if rows else None)
b.ib.disconnect()
PY
