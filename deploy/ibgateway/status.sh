#!/bin/bash
# Human-readable live-bot status board (run on the VPS anytime).
set -u
APP=/opt/autonomous-trade-alerts
EASTERN=$(TZ=America/Toronto date +"%Y-%m-%d %I:%M:%S %p %Z")

echo "============================================"
echo " LIVE BOT STATUS  ($EASTERN)"
echo "============================================"
echo
echo "-- Services --"
# systemctl is-active exits non-zero for inactive/failed; still print that state.
printf "xvfb:              %s\n" "$(systemctl is-active xvfb 2>/dev/null || true)"
printf "ibgateway:         %s\n" "$(systemctl is-active ibgateway 2>/dev/null || true)"
printf "live-worker.timer: %s\n" "$(systemctl is-active live-worker.timer 2>/dev/null || true)"
printf "gateway-health:    %s\n" "$(systemctl is-active gateway-health.timer 2>/dev/null || true)"
if ss -ltn 2>/dev/null | grep -q ':4002'; then
  echo "API port 4002:     LISTEN"
else
  echo "API port 4002:     DOWN"
fi
echo
echo "-- Last worker journal lines --"
journalctl -u live-worker.service -n 8 --no-pager 2>/dev/null | sed 's/^/  /' || echo "  (none)"
echo
echo "-- Last cycle decisions --"
python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

p = Path("/opt/autonomous-trade-alerts/state_live/last_cycle.json")
if not p.exists():
    print("  No last_cycle.json yet (wait for next 5m worker run after deploy).")
    raise SystemExit(0)
raw = json.loads(p.read_text(encoding="utf-8"))
age = None
try:
    at = datetime.fromisoformat(raw.get("at_utc", "").replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - at).total_seconds() / 60.0
except Exception:
    pass
print(f"  ok:           {raw.get('ok')}")
print(f"  when:         {raw.get('at_eastern') or raw.get('at_utc')}")
if age is not None:
    print(f"  age_minutes:  {age:.1f}")
print(f"  mode:         {raw.get('mode')}")
print(f"  price_source: {raw.get('price_source')}")
print(f"  rth_ok:       {raw.get('rth_ok')}")
print(f"  cash_usd:     {raw.get('cash_usd')}")
print(f"  actions:      {raw.get('actions') or []}")
if raw.get("error"):
    print(f"  error:        {raw.get('error')}")
if raw.get("skipped"):
    print(f"  skipped:      {raw.get('skipped')}")
print("  decisions:")
for d in raw.get("decisions") or []:
    print(
        f"    {d.get('symbol')}: px={d.get('price')} signal={d.get('signal')} "
        f"plan={d.get('plan')} action={d.get('action')} "
        f"shares={d.get('shares')} peak={d.get('peak')} trough={d.get('trough')}"
    )
    if d.get("signal_reason"):
        print(f"      reason: {d.get('signal_reason')}")
PY
echo
echo "-- Sleeve state --"
python3 - <<'PY'
import json
from pathlib import Path
p = Path("/opt/autonomous-trade-alerts/state_live/state.json")
if not p.exists():
    print("  (no state.json)")
    raise SystemExit(0)
s = json.loads(p.read_text(encoding="utf-8"))
print(f"  cash_usd: {s.get('cash_usd')}")
for sym, row in (s.get("assets") or {}).items():
    print(
        f"  {sym}: shares={row.get('shares')} last={row.get('last_price')} "
        f"peak={row.get('peak')} trough={row.get('trough')}"
    )
PY
echo
echo "Tip: from Windows PowerShell run:  .\\deploy\\ibgateway\\check_bot.ps1"
echo "============================================"

# Optional: EMAIL=1 ./status.sh  → email this board once
if [ "${EMAIL:-0}" = "1" ]; then
  cd "$APP"
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
  if [ -n "${GMAIL_USER:-}" ] && [ -n "${GMAIL_APP_PASSWORD:-}" ] && [ -n "${ALERT_TO_EMAIL:-}" ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
    BODY=$(bash "$0" | sed '/Tip:/,$d')
    python - <<PY
from app.notifier import send_signal_email
body = """$BODY"""
print("email_sent" if send_signal_email("Live bot status", body) else "email_skipped")
PY
  fi
fi
