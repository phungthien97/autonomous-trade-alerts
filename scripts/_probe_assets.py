"""Show state_live assets / sleeve book vs equal target."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
st = json.loads((ROOT / "state_live" / "state.json").read_text(encoding="utf-8"))
cfg = json.loads((ROOT / "state_live" / "config.json").read_text(encoding="utf-8"))
assets = st.get("assets") or {}
print("use_account_cash", cfg.get("use_account_cash"))
print("symbols", cfg.get("symbols"))
print("total_cash", cfg.get("total_cash"))
print("--- assets ---")
for sym, row in sorted(assets.items()):
    if isinstance(row, dict):
        print(sym, {k: row.get(k) for k in ("shares", "cash", "peak", "trough", "last_price", "reason")})
    else:
        print(sym, row)

# Equal target in native CAD using equity / n
equity = float(st.get("broker_equity_usd") or 0)
n = len(cfg.get("symbols") or []) or 1
rate = float(st.get("usd_cad_rate") or 0) or None
print("equity_native", equity, "n", n, "equal_native", equity / n)
if rate:
    print("equal_usd", (equity / n) / rate)
    print("spendable_usd", st.get("spendable_usd"))
