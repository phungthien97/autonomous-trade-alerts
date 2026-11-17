#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict

from app.broker.ibkr import IbkrBroker


def main() -> int:
    b = IbkrBroker()
    by: dict[str, dict[str, str]] = defaultdict(dict)
    for av in b.ib.accountValues():
        by[av.tag][av.currency or ""] = av.value
    want = (
        "TotalCashValue",
        "NetLiquidation",
        "GrossPositionValue",
        "AvailableFunds",
        "AccruedCash",
        "ExchangeRate",
        "CashBalance",
    )
    for tag in want:
        print(tag, dict(by.get(tag) or {}))
    s = b.get_account_snapshot()
    print(
        "snap",
        "ccy=",
        getattr(s, "account_currency", None),
        "rate=",
        s.usd_cad_rate,
        "cash=",
        round(s.cash_usd, 2),
        "eq=",
        round(s.equity_usd, 2),
        "spendable=",
        round(s.spendable_usd, 2),
        "gross=",
        None if s.gross_position_value_usd is None else round(s.gross_position_value_usd, 2),
    )
    b.ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
