#!/usr/bin/env python3
"""Probe IBKR paper account tags for never-borrow / same-day turnover (R4)."""
from __future__ import annotations

import asyncio
import os

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB

TAGS = (
    "TotalCashValue",
    "CashBalance",
    "SettledCash",
    "AvailableFunds",
    "FullAvailableFunds",
    "BuyingPower",
    "ExcessLiquidity",
    "NetLiquidation",
    "EquityWithLoanValue",
    "InitMarginReq",
    "MaintMarginReq",
    "LookAheadAvailableFunds",
    "Cushion",
    "ExchangeRate",
)


def main() -> int:
    host = os.environ.get("IB_HOST", "127.0.0.1")
    port = int(os.environ.get("IB_PORT", "4002"))
    client_id = int(os.environ.get("IB_CLIENT_ID", "92"))
    ib = IB()
    print(f"connecting {host}:{port} clientId={client_id}")
    ib.connect(host, port, clientId=client_id)
    print("account", ib.managedAccounts())
    ib.sleep(1.5)

    rows: dict[tuple[str, str], float] = {}
    for av in ib.accountValues():
        if av.tag not in TAGS:
            continue
        try:
            rows[(av.tag, av.currency or "")] = float(av.value)
        except (TypeError, ValueError):
            continue

    ib.disconnect()

    print()
    print(f"{'tag':<28} {'ccy':<6} value")
    for (tag, ccy), val in sorted(rows.items()):
        print(f"{tag:<28} {ccy:<6} {val:,.4f}")

    # Policy helpers (USD prefer, else BASE/CAD)
    def pick(tag: str) -> float | None:
        for ccy in ("USD", "", "BASE", "CAD"):
            if (tag, ccy) in rows:
                return rows[(tag, ccy)]
        return None

    cash = pick("TotalCashValue")
    avail = pick("AvailableFunds")
    bp = pick("BuyingPower")
    settled = pick("SettledCash")
    excess = pick("ExcessLiquidity")
    print()
    print("POLICY_PICKS")
    print(f"  cash_usd_candidate=TotalCashValue -> {cash}")
    print(f"  spendable_same_day_candidate=AvailableFunds -> {avail}")
    print(f"  buying_power_leverage=BuyingPower -> {bp}  (DO NOT use for never-borrow)")
    print(f"  SettledCash -> {settled}")
    print(f"  ExcessLiquidity -> {excess}")

    if cash is not None and bp is not None and bp > cash * 1.05:
        print("R4_NOTE: BuyingPower > TotalCashValue — margin leverage present; never-borrow must ignore BP.")
    if avail is not None and cash is not None and avail >= cash - 1e-6:
        print("R4_NOTE: AvailableFunds >= TotalCashValue — OK same-day spendable floor.")
    if cash is not None and avail is not None and bp is not None:
        print("R4_FIELDS_OK")
        return 0
    print("R4_FIELDS_INCOMPLETE")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
