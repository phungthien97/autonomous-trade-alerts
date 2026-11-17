#!/usr/bin/env python3
"""One-shot: finish paper reset after flatten already flat at broker."""
from __future__ import annotations

from pathlib import Path

from app.broker.ibkr import IbkrBroker
from app.live.config import load_live_config
from app.live.paper_reset import apply_state_reset, backup_live_files, redistribute_sleeve_cash
from app.paths import LivePaths


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = LivePaths(project_root=root)
    cfg = load_live_config(paths.config_path)
    symbols = list(cfg.symbols)
    broker = IbkrBroker(dry_run=False)
    try:
        left = {
            s: q
            for s, q in broker.get_positions().items()
            if q > 1e-9 and s in symbols
        }
        print("left", left)
        if left:
            raise SystemExit(f"still long: {left}")
        snap = broker.get_account_snapshot()
        prices, _bars, _closes = broker.latest_hourly_closes(symbols, use_rth=True)
        bak = backup_live_files(paths, Path("/tmp"))
        print("backup", bak)
        sleeve = redistribute_sleeve_cash(symbols, prices, float(snap.spendable_usd))
        apply_state_reset(
            paths,
            symbols=symbols,
            total_cash=float(snap.equity_usd),
            sleeve_cash=sleeve,
            use_account_cash=True,
        )
        print(
            "ok equity=",
            snap.equity_usd,
            "spendable=",
            snap.spendable_usd,
            "cash=",
            snap.cash_usd,
        )
        print("sleeve", sleeve)
    finally:
        ib = getattr(broker, "ib", None)
        if ib is not None and getattr(ib, "isConnected", lambda: False)():
            ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
