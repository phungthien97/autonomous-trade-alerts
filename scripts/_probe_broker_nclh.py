#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path("/opt/autonomous-trade-alerts")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> None:
    from app.broker.ibkr import IbkrBroker

    # Match live-worker client id if possible
    broker = IbkrBroker(client_id=1)
    broker.connect()
    try:
        pos = broker.get_positions()
        print("positions", {k: v for k, v in sorted(pos.items()) if abs(float(v)) > 1e-9})
        snap = broker.get_account_snapshot()
        print(
            "cash",
            getattr(snap, "cash_usd", None),
            "af",
            getattr(snap, "available_funds_usd", None),
            "equity",
            getattr(snap, "equity_usd", None),
            "gross",
            getattr(snap, "gross_position_value_usd", None),
        )
        ib = getattr(broker, "ib", None) or getattr(broker, "_ib", None)
        if ib is not None:
            oo = list(ib.openOrders())
            print("openOrders", len(oo))
            for o in oo:
                print(
                    " order",
                    getattr(o, "orderId", None),
                    getattr(o, "action", None),
                    getattr(o, "totalQuantity", None),
                    getattr(getattr(o, "contract", None), "symbol", None),
                    getattr(o, "orderType", None),
                    getattr(o, "tif", None),
                )
            trades = list(ib.trades())
            recent = [t for t in trades if getattr(getattr(t, "contract", None), "symbol", "") == "NCLH"]
            print("NCLH trades", len(recent))
            for t in recent[-15:]:
                c = t.contract
                o = t.order
                s = t.orderStatus
                print(
                    " trade",
                    o.orderId,
                    o.action,
                    o.totalQuantity,
                    s.status,
                    "filled",
                    s.filled,
                    "remaining",
                    s.remaining,
                    "why",
                    getattr(s, "whyHeld", None),
                )
            # any non-flat positions via portfolio
            for item in ib.portfolio():
                if abs(float(item.position)) > 1e-9:
                    print(
                        "portfolio",
                        item.contract.symbol,
                        item.position,
                        item.marketPrice,
                        item.marketValue,
                        item.account,
                    )
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
