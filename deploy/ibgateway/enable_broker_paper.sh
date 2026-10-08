#!/bin/bash
set -euo pipefail
cd /opt/autonomous-trade-alerts
python3 <<'PY'
import json
from pathlib import Path
c = json.loads(Path("state_live/config.json").read_text())
s = json.loads(Path("state_live/state.json").read_text())
print("mode", c.get("mode"))
print("trading_enabled", c.get("trading_enabled"))
print("cash_usd", s.get("cash_usd"))
for sym, row in (s.get("assets") or {}).items():
    print(sym, {k: row.get(k) for k in ("shares", "cash", "peak", "trough", "last_price")})
q = Path("state_live/queue.json")
print("queue", q.read_text()[:500] if q.exists() else "none")
audit = sorted(Path("state_live/audit").glob("*.jsonl"))
print("audit_files", [p.name for p in audit[-3:]])
if audit:
    lines = audit[-1].read_text().strip().splitlines()
    print("audit_tail", lines[-3:] if lines else [])
PY

sudo cp /tmp/live-worker.service /tmp/live-worker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now live-worker.timer
systemctl status live-worker.timer --no-pager || true
systemctl list-timers live-worker.timer --no-pager || true
echo DONE
