#!/bin/bash
set -euo pipefail
APP=/opt/autonomous-trade-alerts
pid=$(cat "$APP/logs/picker_dryrun.pid")
ps -p "$pid" -o pid,etime,pcpu,pmem,state,cmd --no-headers
echo "--- open files (ib/api hints) ---"
ls -l "/proc/$pid/fd" 2>/dev/null | wc -l
echo "--- recent gateway / ibc ---"
tail -5 /home/ubuntu/ibc/logs/gateway-health.log 2>/dev/null || true
# Count how far into S&P if process has any temp; otherwise just note silence is expected
echo "--- note: fetch is quiet until all symbols scored; ~503 * ~1-3s ≈ 10-40min ---"
