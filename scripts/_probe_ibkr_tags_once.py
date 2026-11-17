"""Dump raw IBKR accountValues tags for currency diagnosis."""
from __future__ import annotations

import os
from collections import defaultdict

os.environ["IB_CLIENT_ID"] = os.environ.get("DASHBOARD_IB_CLIENT_ID", "9")

from app.broker.ibkr import IbkrBroker, _pick_account_amount, _usd_exchange_rate


def main() -> None:
    broker = IbkrBroker()
    try:
        by_tag: dict[str, dict[str, float]] = defaultdict(dict)
        for item in broker.ib.accountValues():
            try:
                value = float(item.value)
            except (TypeError, ValueError):
                continue
            by_tag[item.tag][item.currency or ""] = value

        interesting = [
            "NetLiquidation",
            "TotalCashValue",
            "AvailableFunds",
            "BuyingPower",
            "GrossPositionValue",
            "AccruedCash",
            "CashBalance",
            "ExchangeRate",
            "$LEDGER-ExchangeRate",
            "StockMarketValue",
            "UnrealizedPnL",
            "RealizedPnL",
        ]
        print("=== SELECTED TAGS ===")
        for tag in interesting:
            row = dict(by_tag.get(tag) or {})
            if row:
                print(f"  {tag}: {row}")
            else:
                print(f"  {tag}: (missing)")

        print("\n=== PICK RESULTS ===")
        for tag in [
            "NetLiquidation",
            "TotalCashValue",
            "AvailableFunds",
            "GrossPositionValue",
            "AccruedCash",
        ]:
            amt, ccy = _pick_account_amount(by_tag, tag)
            print(f"  {tag}: {amt} {ccy}")
        print(f"  usd_rate: {_usd_exchange_rate(by_tag)}")

        snap = broker.get_account_snapshot()
        print("\n=== SNAPSHOT ===")
        print(snap)
        print(f"  spendable_native={snap.spendable_native}")
        print(f"  spendable_usd={snap.spendable_usd}")

        pos = broker.get_positions()
        print("\n=== POSITIONS ===")
        print(pos)
        prices = getattr(broker, "last_prices", None) or {}
        print("prices:", prices)
    finally:
        broker.ib.disconnect()


if __name__ == "__main__":
    main()
