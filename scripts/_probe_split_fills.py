"""Inspect fills + whether buy sizing used CAD-as-USD."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from app.account_snapshot import to_usd
from app.broker.ibkr import IbkrBroker
from app.picker.sizing import sleeve_buy_budget


def main() -> None:
    root = Path("state_live")
    cfg = json.loads((root / "config.json").read_text())
    state = json.loads((root / "state.json").read_text())
    lc = json.loads((root / "last_cycle.json").read_text()) if (root / "last_cycle.json").exists() else {}

    print("=== CONFIG ===")
    print("symbols", cfg.get("symbols"))
    print("total_cash", cfg.get("total_cash"), "use_account_cash", cfg.get("use_account_cash"))

    print("\n=== STATE TOP ===")
    for k in (
        "available_funds_usd",
        "spendable_usd",
        "usd_cad_rate",
        "account_currency",
        "cash_usd",
        "broker_equity_usd",
    ):
        print(f"  {k}: {state.get(k)}")

    assets = state.get("assets") or {}
    print("\n=== STATE ASSETS ===")
    for sym in cfg.get("symbols") or sorted(assets):
        row = assets.get(sym) or {}
        print(
            f"  {sym}: shares={row.get('shares')} cash={row.get('cash')} "
            f"last_price={row.get('last_price')} last_action={row.get('last_action')}"
        )

    print("\n=== LAST CYCLE ===")
    print(
        {
            k: lc.get(k)
            for k in (
                "at_eastern",
                "at_utc",
                "spendable_usd",
                "available_funds_usd",
                "usd_cad_rate",
                "account_currency",
                "actions",
            )
        }
    )
    for d in lc.get("decisions") or []:
        print(" ", d)

    trades_path = root / "trades.csv"
    print("\n=== RECENT TRADES ===")
    if trades_path.exists():
        rows = list(csv.DictReader(trades_path.open(encoding="utf-8")))
        for row in rows[-30:]:
            print(
                " ",
                {
                    k: row.get(k)
                    for k in (
                        "ts",
                        "symbol",
                        "side",
                        "qty",
                        "price",
                        "notional",
                        "status",
                        "reason",
                    )
                    if k in row or True
                },
            )
        print(f"(total trade rows: {len(rows)})")
        # show header
        if rows:
            print("headers:", list(rows[0].keys()))

    # Live broker reconstruction
    broker = IbkrBroker()
    try:
        snap = broker.get_account_snapshot()
        pos = broker.get_positions()
        symbols = list(cfg.get("symbols") or [])
        prices, _, _ = broker.latest_hourly_closes(symbols)
        rate = snap.usd_cad_rate
        n = len(symbols)
        print("\n=== RECONSTRUCTION ===")
        print(f"rate={rate} equity_cad={snap.equity_usd} cash_cad={snap.cash_usd}")
        equal_usd = to_usd(snap.equity_usd / n, account_currency="CAD", usd_cad_rate=rate)
        equal_cad = snap.equity_usd / n
        print(f"equal NAV/{n}: {equal_cad:.2f} CAD = {equal_usd:.2f} USD")
        # Bug: treat CAD equal as USD budget
        bug_budget = equal_cad
        print(f"bug budget (CAD-as-USD)={bug_budget:.2f}")

        print("\nLongs vs correct equal vs CAD-as-USD:")
        for s, q in sorted(pos.items()):
            px = prices.get(s)
            if not px:
                continue
            mtm = q * px
            # reverse-engineer: shares ≈ floor(budget/px_fill). Compare to budgets.
            print(
                f"  {s}: qty={q} px={px} mtm={mtm:.2f} "
                f"qty_if_equal_usd={int(equal_usd // px)} "
                f"qty_if_cad_as_usd={int(bug_budget // px)} "
                f"ratio_mtm/equal={mtm / equal_usd:.3f} "
                f"ratio_mtm/bug={mtm / bug_budget:.3f}"
            )

        flats = [s for s in symbols if float(pos.get(s) or 0) <= 0]
        longs = [s for s in symbols if float(pos.get(s) or 0) > 0]
        correct = sleeve_buy_budget(snap.spendable_usd, n, len(longs))
        bug_flat = snap.spendable_native / max(1, len(flats))
        print(f"\nFlat budgets now: correct_usd={correct:.2f} bug_cad_as_usd={bug_flat:.2f}")
        for s in flats:
            px = prices.get(s)
            print(
                f"  {s}: px={px} correct_sh={int(correct // px) if px else None} "
                f"bug_sh={int(bug_flat // px) if px else None}"
            )
    finally:
        broker.ib.disconnect()

    # Check whether deployed worker code converts FX
    worker = Path("app/live_worker.py").read_text(encoding="utf-8")
    snap_py = Path("app/account_snapshot.py").read_text(encoding="utf-8")
    print("\n=== DEPLOYED CODE HINTS ===")
    print("live_worker uses spendable_usd:", "snapshot.spendable_usd" in worker)
    print("account_snapshot has to_usd:", "def to_usd" in snap_py)
    print("account_snapshot spendable_usd uses to_usd:", "to_usd(" in snap_py and "spendable_usd" in snap_py)


if __name__ == "__main__":
    main()
