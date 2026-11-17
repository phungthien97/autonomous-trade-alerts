#!/usr/bin/env bash
# Wait for US RTH, flatten all longs, equal-reset sleeves, resume live-worker.
set -euo pipefail
cd /opt/autonomous-trade-alerts
export PYTHONPATH=.
LOG=/tmp/paper_flatten_rth.log
echo "=== flatten schedule start $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOG"
# client id away from live worker (1) and dashboard (9)
export IB_CLIENT_ID=97
./.venv/bin/python scripts/paper_account_reset.py --execute --wait-rth 2>&1 | tee -a "$LOG"
echo "=== flatten schedule done $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=$? ===" | tee -a "$LOG"
