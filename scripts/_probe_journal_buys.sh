#!/bin/bash
set -euo pipefail
echo "=== cycles with non-empty actions ==="
journalctl -u live-worker.service --since '2026-10-27' --no-pager 2>/dev/null \
  | grep -F "actions" \
  | grep -v "actions': []" \
  | grep -v 'actions": []' \
  | tail -60 || true

echo
echo "=== first lines with usd_cad_rate ==="
journalctl -u live-worker.service --since '2026-10-27' --no-pager 2>/dev/null \
  | grep -m 8 -F "usd_cad_rate" || true

echo
echo "=== file mtimes for sizing code ==="
ls -la --time-style=long-iso /opt/autonomous-trade-alerts/app/account_snapshot.py \
  /opt/autonomous-trade-alerts/app/broker/ibkr.py \
  /opt/autonomous-trade-alerts/app/live_worker.py

echo
echo "=== sample morning cycle money fields ==="
journalctl -u live-worker.service --since '2026-10-28 10:00' --until '2026-10-28 11:00' --no-pager 2>/dev/null \
  | grep -F "spendable_usd" | head -3 || true

echo
echo "=== sample afternoon cycle money fields ==="
journalctl -u live-worker.service --since '2026-10-28 16:00' --no-pager 2>/dev/null \
  | grep -F "spendable_usd" | head -3 || true

echo
echo "=== python extract share/spendable timeline ==="
PYTHONPATH=/opt/autonomous-trade-alerts /opt/autonomous-trade-alerts/.venv/bin/python - <<'PY'
import re, subprocess
out = subprocess.check_output(
    ["journalctl", "-u", "live-worker.service", "--since", "2026-10-28", "--no-pager"],
    text=True, errors="replace",
)
pat = re.compile(
    r"^(?P<ts>\w+\s+\d+\s+[\d:]+).*?"
    r"'cash_usd': (?P<cash>[^,]+).*?"
    r"'spendable_usd': (?P<spend>[^,]+).*?"
    r"(?:'usd_cad_rate': (?P<rate>[^,]+).*?)?"
    r"'book_equity': (?P<eq>[^,]+)",
    re.M,
)
# also pull share counts from decisions
share_pat = re.compile(
    r"'symbol': '(?P<sym>P|HUM|AMGN|FICO|VLO)'.*?'shares': (?P<sh>[0-9.]+)"
)
prev = None
for line in out.splitlines():
    if "spendable_usd" not in line:
        continue
    m = re.search(r"'cash_usd': ([^,]+).*'spendable_usd': ([^,]+)", line)
    rate_m = re.search(r"'usd_cad_rate': ([^,}\s]+)", line)
    shares = {m2.group("sym"): float(m2.group("sh")) for m2 in share_pat.finditer(line)}
    if not m:
        continue
    cash, spend = float(m.group(1)), float(m.group(2))
    rate = float(rate_m.group(1)) if rate_m else None
    key = (round(cash,0), round(spend,0), None if rate is None else round(rate,4), tuple(sorted(shares.items())))
    if key == prev:
        continue
    prev = key
    ts = " ".join(line.split()[:3])
    ratio = spend/cash if cash else None
    print(f"{ts} cash={cash:.0f} spend={spend:.0f} rate={rate} spend/cash={ratio} shares={shares}")
PY
