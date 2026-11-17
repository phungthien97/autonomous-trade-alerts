#!/usr/bin/env python3
"""Probe IBKR for CAD/USD FX: account ExchangeRate + IDEALPRO ticker."""
from __future__ import annotations

from app.broker.ibkr import IbkrBroker


def main() -> int:
    b = IbkrBroker()
    ib = b.ib
    print("managed", ib.managedAccounts())

    # 1) AccountValues ExchangeRate / any FX-ish tags
    fx_tags = {}
    for av in ib.accountValues():
        tag = av.tag or ""
        if "Exchange" in tag or "Rate" in tag or tag in {
            "ExchangeRate",
            "CurrencyExchangeRate",
            "FxCashBalance",
        }:
            fx_tags.setdefault(tag, {})[av.currency or ""] = av.value
    print("account_fx_tags", fx_tags or "(none)")

    # 2) IDEALPRO USD.CAD (or CAD.USD)
    from ib_insync import Forex

    for pair in ("USD.CAD", "CAD.USD"):
        contract = Forex(pair)
        qualified = ib.qualifyContracts(contract)
        print("forex_qualify", pair, bool(qualified), qualified)
        if not qualified:
            continue
        tickers = ib.reqTickers(qualified[0])
        ib.sleep(2)
        for t in tickers:
            print(
                "ticker",
                pair,
                "bid",
                t.bid,
                "ask",
                t.ask,
                "last",
                t.last,
                "close",
                t.close,
                "marketPrice",
                getattr(t, "marketPrice", lambda: None)(),
            )

    # 3) What snapshot does today
    s = b.get_account_snapshot()
    print(
        "snapshot",
        "ccy=",
        s.account_currency,
        "rate=",
        s.usd_cad_rate,
        "cash=",
        s.cash_usd,
        "equity=",
        s.equity_usd,
    )
    b.ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
