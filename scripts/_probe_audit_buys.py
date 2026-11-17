"""Scan audit events for BUY fills and sizing fields."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    path = Path("state_live/audit/events.jsonl")
    if not path.exists():
        print("missing", path)
        return
    buys = []
    rate_events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        blob = json.dumps(ev).upper()
        if "USD_CAD_RATE" in blob or "SPENDABLE" in blob:
            rate_events.append(ev)
        side = str(ev.get("side") or "").upper()
        action = str(ev.get("action") or "").upper()
        et = str(ev.get("type") or ev.get("event") or "").upper()
        sym = str(ev.get("symbol") or "")
        if side == "BUY" or action == "BUY" or "BUY" in et or (
            sym in {"P", "AMGN", "HUM", "FICO", "VLO"} and ("FILL" in et or "ORDER" in et)
        ):
            buys.append(ev)

    print(f"buys/order-ish events: {len(buys)}")
    print(f"spendable/rate-ish events: {len(rate_events)}")
    print("\n=== LAST 50 BUY/ORDER EVENTS ===")
    for ev in buys[-50:]:
        keys = [
            "ts",
            "at",
            "at_utc",
            "type",
            "event",
            "symbol",
            "side",
            "action",
            "qty",
            "quantity",
            "filled_qty",
            "price",
            "avg_price",
            "status",
            "buy_cap",
            "spendable_usd",
            "available_funds_usd",
            "usd_cad_rate",
            "account_currency",
            "reason",
            "notional",
        ]
        compact = {k: ev.get(k) for k in keys if k in ev}
        if not compact:
            compact = {k: ev.get(k) for k in list(ev)[:15]}
        print(compact)

    print("\n=== LAST 20 SPENDABLE/RATE EVENTS ===")
    for ev in rate_events[-20:]:
        keys = [
            "ts",
            "at",
            "type",
            "event",
            "symbol",
            "spendable_usd",
            "available_funds_usd",
            "usd_cad_rate",
            "account_currency",
            "cash_usd",
        ]
        print({k: ev.get(k) for k in keys if k in ev} or {k: ev.get(k) for k in list(ev)[:12]})

    # Also dump last_cycle history if any backups
    for p in sorted(Path("state_live").glob("**/last_cycle*.json")):
        print("\nfound", p)


if __name__ == "__main__":
    main()
