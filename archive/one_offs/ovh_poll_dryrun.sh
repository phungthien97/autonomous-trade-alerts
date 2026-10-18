#!/bin/bash
set -euo pipefail
APP=/opt/autonomous-trade-alerts
cd "$APP"
pid=$(cat logs/picker_dryrun.pid 2>/dev/null || echo none)
echo "pid=$pid"
if [ "$pid" != "none" ] && kill -0 "$pid" 2>/dev/null; then
  ps -p "$pid" -o pid,etime,pcpu,state,cmd --no-headers
else
  echo "dry-run not running"
fi
echo "--- latest log tail ---"
ls -t logs/picker_dryrun_*.log 2>/dev/null | head -1 | xargs -r tail -40
echo "--- ranking_runs ---"
ls -la state_picker/ranking_runs/ 2>&1 | head -20
