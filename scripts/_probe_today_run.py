"""One-off: summarize Monday soft-rotate / Nov 2 live run on OVH."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

APP = Path("/opt/autonomous-trade-alerts")
DAY = "2026-11-02"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    active = _load(APP / "state_picker" / "active_selection.json")
    pending = _load(APP / "state_picker" / "pending_selection.json")
    config = _load(APP / "state_live" / "config.json")
    state = _load(APP / "state_live" / "state.json")
    last = _load(APP / "state_live" / "last_cycle.json")

    print("=== PENDING ===")
    print(
        "status=",
        pending.get("status"),
        "apply_after=",
        pending.get("apply_after"),
        "run_id=",
        pending.get("run_id"),
    )
    print("symbols=", [s["symbol"] for s in pending.get("symbols", [])])

    print("=== ACTIVE ===")
    print("applied_at=", active.get("applied_at"), "run_id=", active.get("run_id"))
    for s in active.get("symbols", []):
        print(
            f"  {s['symbol']:6} exit_only={bool(s.get('exit_only'))} "
            f"awaiting={bool(s.get('awaiting_first_buy'))} joined={s.get('joined_at')}"
        )

    print("=== CONFIG ===")
    print("symbols=", config.get("symbols"))
    print("budget=", config.get("trading_budget_usd"))
    print("daily_order_cap=", config.get("daily_order_cap"))

    print("=== STATE SHARES / FLAGS ===")
    assets = state.get("assets") or {}
    for sym, row in assets.items():
        print(
            f"  {sym:6} shares={row.get('shares')} peak={row.get('peak')} "
            f"trough={row.get('trough')} exit_pending={row.get('exit_pending')} "
            f"last={row.get('last_price')}"
        )
    print(
        "orders_today=",
        state.get("orders_today"),
        state.get("orders_today_by_symbol"),
    )
    print(
        "budget_state=",
        state.get("trading_budget_usd"),
        "invested=",
        last.get("invested_usd"),
        "spendable=",
        last.get("spendable_usd"),
        "gross=",
        last.get("gross_position_value_usd"),
    )

    print("=== LAST CYCLE ===")
    print(
        "ok=",
        last.get("ok"),
        "at=",
        last.get("at_eastern") or last.get("at_utc"),
        "rth=",
        last.get("rth_ok"),
        "src=",
        last.get("price_source"),
        "actions=",
        last.get("actions"),
    )
    for d in last.get("decisions") or []:
        print(
            f"  {d.get('symbol'):6} sh={d.get('shares')} sig={d.get('signal')} "
            f"gate={d.get('gate')} plan={d.get('plan')} :: {d.get('signal_reason')}"
        )

    # Sleeve notionals from last prices
    print("=== NOTIONAL SNAPSHOT (shares * last_cycle price) ===")
    px = {d["symbol"]: float(d["price"]) for d in (last.get("decisions") or []) if d.get("price")}
    total = 0.0
    for sym, row in assets.items():
        sh = float(row.get("shares") or 0)
        if sh <= 0:
            continue
        p = px.get(sym) or float(row.get("last_price") or 0)
        n = sh * p
        total += n
        print(f"  {sym:6} {sh:10g} x {p:.2f} = {n:,.2f}")
    print(f"  TOTAL long mark = {total:,.2f}")
    bud = float(config.get("trading_budget_usd") or 0)
    print(f"  budget = {bud:,.2f}  unused≈{max(0, bud-total):,.2f}")

    print("=== AUDIT EVENTS ON", DAY, "===")
    audit = APP / "state_live" / "audit" / "events.jsonl"
    types: Counter[str] = Counter()
    by_sym: dict[str, list] = defaultdict(list)
    day_rows = []
    for line in audit.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = str(o.get("ts") or "")
        if DAY not in ts:
            continue
        day_rows.append(o)
        types[str(o.get("event") or o.get("type") or "?")] += 1
        sym = o.get("symbol") or (o.get("payload") or {}).get("symbol")
        if sym:
            by_sym[str(sym)].append(o)

    print("n=", len(day_rows), "types=", dict(types))
    for o in day_rows:
        ev = o.get("event") or o.get("type")
        payload = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        sym = o.get("symbol") or payload.get("symbol")
        side = o.get("side") or payload.get("side")
        qty = o.get("quantity") or payload.get("quantity") or payload.get("filled_qty")
        status = o.get("status") or payload.get("status")
        reason = o.get("reason") or payload.get("reason")
        print(
            f"  {o.get('ts')} {ev} {sym} {side} qty={qty} status={status} reason={reason}"
        )
        # compact extras for fills
        if ev in {"fill", "order", "submit", "place"} or "fill" in str(ev):
            print("    ", {k: o.get(k) for k in o if k not in {"payload"}} | (
                {"payload": payload} if payload else {}
            ))

    # Journal snippets around apply / buys
    print("=== JOURNAL APPLY / BUY HINTS ===")
    import subprocess

    out = subprocess.check_output(
        [
            "bash",
            "-lc",
            "journalctl -u live-worker.service --since '2026-11-02 00:00:00' --no-pager 2>/dev/null | "
            "grep -E 'apply|soft.rotate|pending|BUY|SELL|submitted|filled|blocked|exit_only|awaiting|New picker|inflight|unused|seeded' | head -n 200",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    print(out or "(no matches)")


if __name__ == "__main__":
    main()
