"""Show current live sleeve market-value distribution on OVH."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "state_live" / "state.json"
if not path.exists():
    raise SystemExit(f"missing {path}")

st = json.loads(path.read_text(encoding="utf-8"))
print("STATE", path)
print("account_currency", st.get("account_currency"))
print("usd_cad_rate", st.get("usd_cad_rate"))
print("fx_rates", st.get("fx_rates"))
print("cash_usd", st.get("cash_usd"))
print("spendable_usd", st.get("spendable_usd"))
print("broker_equity", st.get("broker_equity_usd") or st.get("equity_usd"))
print("gross", st.get("gross_position_value_usd"))

pos = st.get("positions") or []
if isinstance(pos, dict):
    rows = [{"symbol": k, **(v if isinstance(v, dict) else {"shares": v})} for k, v in pos.items()]
else:
    rows = list(pos)

print("--- positions ---")
mvs = []
for r in sorted(rows, key=lambda x: str(x.get("symbol") or "")):
    sym = r.get("symbol")
    sh = float(r.get("shares") or 0)
    px = r.get("last_price") or r.get("price")
    mv = None
    try:
        if px is not None:
            mv = sh * float(px)
            mvs.append((str(sym), sh, float(px), mv))
    except (TypeError, ValueError):
        mvs.append((str(sym), sh, None, None))
    print(f"{sym}: shares={sh} price={px} mv={mv} cash={r.get('cash')}")

longs = [m for m in mvs if m[1] > 0 and m[3] is not None]
if longs:
    vals = [m[3] for m in longs]
    target = sum(vals) / len(vals)
    print("--- longs summary ---")
    print("n_long", len(vals), "min", round(min(vals), 2), "max", round(max(vals), 2), "sum", round(sum(vals), 2))
    print("equal_target_among_longs", round(target, 2))
    for sym, sh, px, mv in sorted(longs, key=lambda x: -x[3]):
        print(f"  {sym}: shares={sh:g} @ {px} → mv={mv:.2f} ({100 * mv / target - 100:+.1f}% vs equal)")

# Active book size from config
cfg_path = ROOT / "state_live" / "config.json"
if cfg_path.exists():
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    syms = list(cfg.get("symbols") or [])
    print("config_symbols", len(syms), syms)
    flat = [s for s in syms if not any(m[0] == s and m[1] > 0 for m in mvs)]
    print("flat_in_book", flat)

lc = ROOT / "state_live" / "last_cycle.json"
if lc.exists():
    last = json.loads(lc.read_text(encoding="utf-8"))
    print("last_cycle_at", last.get("at_eastern") or last.get("at_utc"))
    print("last_actions", last.get("actions"))
