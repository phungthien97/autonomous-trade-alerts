#!/usr/bin/env python3
"""Rewrite today's account_nav equity in native IBKR CAD after bad USD write."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.broker.ibkr import IbkrBroker
from app.live.account_nav import upsert_account_nav
from app.paths import LivePaths


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = LivePaths(project_root=root)
    b = IbkrBroker()
    try:
        s = b.get_account_snapshot()
        print(
            "snap",
            s.account_currency,
            "rate",
            s.usd_cad_rate,
            "equity",
            round(s.equity_usd, 2),
            "cash",
            round(s.cash_usd, 2),
            "spendable_native",
            round(s.spendable_native, 2),
            "spendable_usd",
            round(s.spendable_usd, 2),
        )
        upsert_account_nav(paths.account_nav_path, equity=float(s.equity_usd), at=datetime.now(timezone.utc))
        print("nav_updated", paths.account_nav_path)
    finally:
        b.ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
