"""One-shot: dump live split inputs (cash/AF/FX/positions/budgets)."""
from __future__ import annotations

import json
from math import floor
from pathlib import Path

from app.account_snapshot import compute_spendable, to_usd
from app.live.paths import LivePaths
from app.picker.sizing import sleeve_buy_budget
from app.remote.money import live_money_snapshot
from app.remote.status import load_live_status
from app.remote.ui import _try_ibkr_marks


def main() -> None:
    root = Path(".")
    paths = LivePaths(project_root=root)
    st = load_live_status(paths.state_dir)
    print("=== FILE STATUS ===")
    for k in [
        "account_currency",
        "cash_usd",
        "broker_equity_usd",
        "available_funds_usd",
        "spendable_usd",
        "gross_position_value_usd",
        "accrued_cash_usd",
        "usd_cad_rate",
        "use_account_cash",
        "symbols",
    ]:
        print(f"  {k}: {st.get(k)}")
    print("  positions:")
    for p in st.get("positions") or []:
        print(
            "   ",
            {
                k: p.get(k)
                for k in ("symbol", "shares", "cash", "last_price", "price")
            },
        )
    lc = st.get("last_cycle") or {}
    print(
        "  last_cycle money:",
        {
            k: lc.get(k)
            for k in (
                "spendable_usd",
                "available_funds_usd",
                "usd_cad_rate",
                "account_currency",
            )
        },
    )
    print("  last decisions:")
    for d in lc.get("decisions") or []:
        if not isinstance(d, dict):
            continue
        print(
            "   ",
            {
                k: d.get(k)
                for k in (
                    "symbol",
                    "signal",
                    "signal_reason",
                    "shares",
                    "price",
                    "qty",
                    "buy_cap",
                    "why",
                    "plan_why",
                )
            },
        )

    print("\n=== LIVE IBKR MARKS ===")
    st2 = _try_ibkr_marks(dict(st))
    print("  marks_source:", st2.get("marks_source"))
    if st2.get("marks_error"):
        print("  marks_error:", st2.get("marks_error"))
    for k in [
        "account_currency",
        "cash_usd",
        "broker_equity_usd",
        "available_funds_usd",
        "spendable_usd",
        "gross_position_value_usd",
        "accrued_cash_usd",
        "usd_cad_rate",
    ]:
        print(f"  {k}: {st2.get(k)}")
    print("  positions:")
    for p in st2.get("positions") or []:
        print(
            "   ",
            {
                k: p.get(k)
                for k in ("symbol", "shares", "cash", "last_price", "price")
            },
        )

    cash = float(st2.get("cash_usd") or 0)
    af = st2.get("available_funds_usd")
    af_f = float(af) if isinstance(af, (int, float)) else None
    gross = st2.get("gross_position_value_usd")
    gross_f = float(gross) if isinstance(gross, (int, float)) else None
    ccy = str(st2.get("account_currency") or "CAD")
    rate = st2.get("usd_cad_rate")
    rate_f = float(rate) if isinstance(rate, (int, float)) else None
    spend_n = compute_spendable(cash, af_f, gross_f)
    spend_u = to_usd(spend_n, account_currency=ccy, usd_cad_rate=rate_f)
    print("\n=== SPENDABLE MATH ===")
    print(f"  cash={cash} af={af_f} gross={gross_f} ccy={ccy} rate={rate_f}")
    print(f"  spendable_native={spend_n:.4f}")
    print(f"  spendable_usd={spend_u:.4f}")

    pos = st2.get("positions") or []
    longs = [p for p in pos if float(p.get("shares") or 0) > 0]
    flats = [p for p in pos if float(p.get("shares") or 0) <= 0]
    print(f"  n_long={len(longs)} n_flat={len(flats)} n_total={len(pos)}")
    print("  longs:")
    stock_usd = 0.0
    for p in longs:
        sh = float(p.get("shares") or 0)
        px = p.get("last_price")
        if px is None:
            px = p.get("price")
        px_f = float(px) if isinstance(px, (int, float)) else None
        mv = sh * px_f if px_f is not None else None
        if mv is not None:
            stock_usd += mv
        print(f"    {p.get('symbol')}: {sh} @ {px_f} -> {mv}")
    print(f"  sum long MTM USD={stock_usd:.2f}")
    if rate_f:
        print(f"  sum long MTM CAD≈{stock_usd * rate_f:.2f}")
        print(f"  broker gross={gross_f} vs MTM CAD={stock_usd * rate_f:.2f}")
        print(f"  cash+gross+accrued vs equity:")
        acc = st2.get("accrued_cash_usd")
        acc_f = float(acc) if isinstance(acc, (int, float)) else 0.0
        eq = float(st2.get("broker_equity_usd") or 0)
        print(
            f"    cash({cash})+gross({gross_f})+accrued({acc_f})"
            f"={cash + (gross_f or 0) + acc_f:.2f} equity={eq}"
        )

    n_active = len(pos)
    n_long = len(longs)
    budget = sleeve_buy_budget(spend_u, n_active, n_long) if flats else 0.0
    print(f"\n=== SPLIT (worker-style: spendable_usd / flat) ===")
    print(f"  sleeve_buy_budget USD={budget:.2f} (flat={len(flats)})")
    for p in flats:
        px = p.get("last_price")
        if px is None:
            px = p.get("price")
        px_f = float(px) if isinstance(px, (int, float)) else None
        planned = int(floor(budget / px_f)) if px_f and px_f > 0 else None
        print(f"    {p.get('symbol')}: budget={budget:.2f} px={px_f} planned={planned}")

    money = live_money_snapshot(
        positions=pos,
        total_cash=st2.get("total_cash"),
        equity_path=paths.equity_path,
        account_nav_path=paths.account_nav_path,
        symbols=list(st2.get("symbols") or []),
        use_account_cash=True,
        broker_cash=cash,
        broker_equity=float(st2["broker_equity_usd"])
        if isinstance(st2.get("broker_equity_usd"), (int, float))
        else None,
        available_funds=af_f,
        broker_stock_value=gross_f,
        broker_accrued_cash=float(st2["accrued_cash_usd"])
        if isinstance(st2.get("accrued_cash_usd"), (int, float))
        else None,
        account_currency=ccy,
        usd_cad_rate=rate_f,
    )
    print("\n=== DASHBOARD MONEY SNAPSHOT ===")
    print(
        json.dumps(
            {
                "nav": money.get("nav"),
                "cash": money.get("cash"),
                "invested": money.get("invested"),
                "available_funds": money.get("available_funds"),
                "account_currency": money.get("account_currency"),
            },
            indent=2,
        )
    )
    print("  holdings planned:")
    for h in money.get("holdings") or []:
        print(
            "   ",
            {
                k: h.get(k)
                for k in (
                    "symbol",
                    "shares",
                    "price",
                    "stock_value",
                    "buy_budget",
                    "planned_shares",
                )
            },
        )


if __name__ == "__main__":
    main()
