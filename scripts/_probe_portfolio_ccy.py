#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from app.broker.ibkr import IbkrBroker
from app.paths import LivePaths
from app.remote.marks import overlay_ibkr_marks
from app.remote.money import live_money_snapshot
from app.remote.status import load_live_status
from app.remote.ui import _fmt_money


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = LivePaths(project_root=root)
    status = load_live_status(paths.state_dir)
    print(
        "file",
        "ccy=",
        status.get("account_currency"),
        "cash=",
        status.get("cash_usd"),
        "eq=",
        status.get("broker_equity_usd"),
    )
    status = overlay_ibkr_marks(status, broker_factory=IbkrBroker)
    print(
        "marks",
        status.get("marks_source"),
        "ccy=",
        status.get("account_currency"),
        "cash=",
        status.get("cash_usd"),
        "eq=",
        status.get("broker_equity_usd"),
        "rate=",
        status.get("usd_cad_rate"),
    )
    money = live_money_snapshot(
        positions=status.get("positions") or [],
        total_cash=status.get("total_cash"),
        symbols=list(status.get("symbols") or []),
        use_account_cash=True,
        broker_cash=status.get("cash_usd")
        if isinstance(status.get("cash_usd"), (int, float))
        else None,
        broker_equity=status.get("broker_equity_usd")
        if isinstance(status.get("broker_equity_usd"), (int, float))
        else status.get("total_cash"),
        available_funds=status.get("available_funds_usd")
        if isinstance(status.get("available_funds_usd"), (int, float))
        else None,
        broker_stock_value=status.get("gross_position_value_usd")
        if isinstance(status.get("gross_position_value_usd"), (int, float))
        else None,
        broker_accrued_cash=status.get("accrued_cash_usd")
        if isinstance(status.get("accrued_cash_usd"), (int, float))
        else None,
        account_currency=status.get("account_currency"),
        usd_cad_rate=status.get("usd_cad_rate")
        if isinstance(status.get("usd_cad_rate"), (int, float))
        else None,
    )
    ccy = str(money.get("account_currency") or "CAD").upper()
    print(
        "money",
        "ccy=",
        ccy,
        "nav=",
        _fmt_money(money.get("nav"), currency=ccy),
        "cash=",
        _fmt_money(money.get("cash"), currency=ccy),
        "invested=",
        _fmt_money(money.get("invested"), currency=ccy),
        "deploy=",
        _fmt_money(money.get("available_funds"), currency=ccy),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
