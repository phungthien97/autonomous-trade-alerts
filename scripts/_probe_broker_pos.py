"""Dump state_live positions + live IBKR portfolio + recent audit buys."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
st_path = ROOT / "state_live" / "state.json"
st = json.loads(st_path.read_text(encoding="utf-8"))
print("keys", sorted(st.keys()))
print("positions_file", st.get("positions"))
print("cash", st.get("cash_usd"), "gross", st.get("gross_position_value_usd"), "equity", st.get("broker_equity_usd"))

audit = ROOT / "state_live" / "audit.jsonl"
if audit.exists():
    lines = audit.read_text(encoding="utf-8").splitlines()
    print("audit_lines", len(lines))
    buys = []
    for line in lines[-200:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("side") or row.get("action") or "").upper() in {"BUY", "B"} or row.get("signal") == "BUY":
            buys.append(row)
        # also catch filled orders
        if "BUY" in str(row).upper() and ("shares" in row or "quantity" in row or "qty" in row):
            if row not in buys:
                buys.append(row)
    print("--- recent buy-ish audit (last 30) ---")
    for row in buys[-30:]:
        print(
            {
                k: row.get(k)
                for k in (
                    "at",
                    "ts",
                    "symbol",
                    "side",
                    "signal",
                    "shares",
                    "qty",
                    "quantity",
                    "price",
                    "spendable_usd",
                    "cash_usd",
                    "usd_cad_rate",
                    "why",
                    "reason",
                )
                if row.get(k) is not None
            }
        )

print("--- IBKR portfolio ---")
try:
    from app.broker.ibkr import IbkrBroker, connection_settings

    host, port, cid = connection_settings()
    print("connect", host, port, "client", cid)
    broker = IbkrBroker()
    try:
        pos = broker.get_positions()
        snap = broker.get_account_snapshot()
        print("account_currency", snap.account_currency)
        print("usd_cad_rate", snap.usd_cad_rate)
        print("fx_rates", snap.fx_rates)
        print("cash_native", snap.cash_usd)
        print("spendable_native", snap.spendable_native)
        print("spendable_usd", snap.spendable_usd)
        print("equity_native", snap.equity_usd)
        print("gross_native", snap.gross_position_value_usd)
        prices = getattr(broker, "last_prices", None) or {}
        # try to fetch marks via portfolio
        ib = getattr(broker, "ib", None)
        port_rows = []
        if ib is not None:
            for p in ib.portfolio():
                c = p.contract
                sym = getattr(c, "symbol", None)
                port_rows.append(
                    {
                        "symbol": sym,
                        "currency": getattr(c, "currency", None),
                        "position": float(p.position),
                        "marketPrice": float(getattr(p, "marketPrice", 0) or 0),
                        "marketValue": float(getattr(p, "marketValue", 0) or 0),
                        "averageCost": float(getattr(p, "averageCost", 0) or 0),
                    }
                )
        print("get_positions", pos)
        if port_rows:
            longs = [r for r in port_rows if abs(r["position"]) > 0]
            print("n_long", len(longs))
            mvs = [r["marketValue"] for r in longs]
            if mvs:
                target = sum(mvs) / len(mvs)
                print("sum_mv", sum(mvs), "equal_target", target)
                for r in sorted(longs, key=lambda x: -abs(x["marketValue"])):
                    mv = r["marketValue"]
                    print(
                        f"  {r['symbol']} {r['currency']}: pos={r['position']} "
                        f"px={r['marketPrice']} mv={mv:.2f} "
                        f"({100 * mv / target - 100:+.1f}% vs equal) avgCost={r['averageCost']}"
                    )
        else:
            print("no portfolio rows")
    finally:
        try:
            broker.ib.disconnect()
        except Exception:
            pass
except Exception as exc:
    print("IBKR_ERROR", type(exc).__name__, exc)
