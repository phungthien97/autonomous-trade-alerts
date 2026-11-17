"""Deep probe: long notionals vs equal split, flat budgets, state sleeve cash."""
from __future__ import annotations

import json
import os
from math import floor
from pathlib import Path

os.environ.setdefault("IB_CLIENT_ID", "9")

from app.broker.ibkr import IbkrBroker
from app.picker.sizing import sleeve_buy_budget


def main() -> None:
    cfg_path = Path("data/live/config.json")
    state_path = Path("data/live/state.json")
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    print("=== CONFIG ===")
    print("symbols:", cfg.get("symbols"))
    print("use_account_cash:", cfg.get("use_account_cash"))
    print("total_cash:", cfg.get("total_cash"))

    assets = state.get("assets") or {}
    print("\n=== STATE ASSETS ===")
    if isinstance(assets, dict):
        for sym, row in sorted(assets.items()):
            if not isinstance(row, dict):
                continue
            print(
                f"  {sym}:",
                {
                    k: row.get(k)
                    for k in ("shares", "cash", "peak", "trough", "last_price", "last_action")
                },
            )

    broker = IbkrBroker()
    try:
        snap = broker.get_account_snapshot()
        pos = broker.get_positions()
        symbols = list(cfg.get("symbols") or sorted(pos.keys()))
        prices, _bars, _series = broker.latest_hourly_closes(symbols)
        rate = float(snap.usd_cad_rate or 0) or None

        print("\n=== SNAPSHOT ===")
        print(snap)
        print("spendable_native", round(snap.spendable_native, 2))
        print("spendable_usd", round(snap.spendable_usd, 2))
        print("prices", prices)

        longs = [s for s in symbols if float(pos.get(s) or 0) > 0]
        flats = [s for s in symbols if float(pos.get(s) or 0) <= 0]
        n_active = len(symbols)
        n_long = len(longs)

        print("\n=== LONG NOTIONALS ===")
        long_mtm_usd = 0.0
        for s in longs:
            q = float(pos[s])
            px = prices.get(s)
            mv = q * px if px else None
            if mv:
                long_mtm_usd += mv
            cad = mv * rate if (mv is not None and rate) else None
            print(f"  {s}: qty={q} px={px} mtm_usd={mv} mtm_cad={cad}")
        print(f"sum long MTM USD={long_mtm_usd:.2f}")
        if rate:
            print(f"sum long MTM CAD={long_mtm_usd * rate:.2f}")
            print(f"broker GrossPositionValue CAD={snap.gross_position_value_usd}")
            print(
                f"cash+gross+accrued="
                f"{snap.cash_usd + float(snap.gross_position_value_usd or 0) + float(snap.accrued_cash_usd or 0):.2f}"
                f" equity={snap.equity_usd}"
            )

        print("\n=== EQUAL-SPLIT BENCHMARKS ===")
        if rate and n_active:
            eq_cad = snap.equity_usd / n_active
            eq_usd = eq_cad / rate
            print(f"NAV/{n_active}: {eq_cad:.2f} CAD = {eq_usd:.2f} USD")
            cash_gross = (snap.cash_usd + float(snap.gross_position_value_usd or 0)) / n_active
            print(f"(cash+gross)/{n_active}: {cash_gross:.2f} CAD = {cash_gross / rate:.2f} USD")
            for s in longs:
                q = float(pos[s])
                px = prices.get(s)
                mv = q * px if px else None
                if mv is None:
                    continue
                print(
                    f"  {s}: mtm_usd={mv:.2f} vs equal_usd={eq_usd:.2f} "
                    f"ratio={mv / eq_usd:.3f} overshoot_usd={mv - eq_usd:.2f}"
                )

        print("\n=== FLAT BUY BUDGETS (current worker rule) ===")
        budget = sleeve_buy_budget(snap.spendable_usd, n_active, n_long)
        print(
            f"spendable_usd={snap.spendable_usd:.2f} / flats={len(flats)} "
            f"=> budget_usd={budget:.2f} (CAD {budget * rate if rate else 'n/a'})"
        )
        for s in flats:
            px = prices.get(s)
            planned = int(floor(budget / px)) if px and px > 0 else None
            cost = planned * px if planned and px else None
            print(f"  {s}: px={px} planned={planned} cost_usd={cost}")

        # What if someone divided CAD spendable by USD prices (the old bug)?
        print("\n=== IF CAD SPENDABLE / USD PRICE (bug pattern) ===")
        bad_budget = snap.spendable_native / max(1, len(flats))
        print(f"CAD pool/flat={bad_budget:.2f} (would look like USD)")
        for s in flats:
            px = prices.get(s)
            planned = int(floor(bad_budget / px)) if px and px > 0 else None
            print(f"  {s}: planned_if_bug={planned}")

        # Reconstruct approximate fill cost from state cash leftovers?
        print("\n=== STATE SLEEVE CASH vs BROKER ===")
        if isinstance(assets, dict):
            sleeve_cash_sum = 0.0
            for s, row in assets.items():
                if isinstance(row, dict):
                    sleeve_cash_sum += float(row.get("cash") or 0)
            print(f"sum sleeve cash in state={sleeve_cash_sum:.2f}")
            print(f"broker cash={snap.cash_usd:.2f}")
    finally:
        broker.ib.disconnect()


if __name__ == "__main__":
    main()
