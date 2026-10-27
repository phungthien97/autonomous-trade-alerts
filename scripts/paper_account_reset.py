#!/usr/bin/env python3
"""One-time paper reset: flatten longs, redistrib cash, resume live worker.

Default is dry-run (no orders, no file writes, no systemctl).

  python scripts/paper_account_reset.py
  python scripts/paper_account_reset.py --execute --wait-rth
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Place sells, rewrite state_live, toggle systemd (default: dry-run)",
    )
    parser.add_argument(
        "--wait-rth",
        action="store_true",
        help="Block until US regular hours before flattening",
    )
    parser.add_argument(
        "--skip-timer",
        action="store_true",
        help="Do not stop/start live-worker.timer",
    )
    parser.add_argument(
        "--skip-worker-cycle",
        action="store_true",
        help="Do not run a live_worker cycle after resume",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path("/tmp"),
        help="Directory for state backups (default /tmp)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Repo root containing state_live/",
    )
    args = parser.parse_args(argv)

    dry_run = not args.execute
    project_root = args.project_root.resolve()
    _load_dotenv(project_root / ".env")

    # Avoid clashing with the live worker client id.
    os.environ.setdefault("IB_CLIENT_ID", "97")

    from app.broker.ibkr import IbkrBroker
    from app.live.config import load_live_config
    from app.live.paper_reset import (
        apply_state_reset,
        backup_live_files,
        cancel_open_orders,
        flatten_longs,
        plan_reset,
        systemctl,
        wait_until_rth,
    )
    from app.live.session import is_us_equity_rth
    from app.paths import LivePaths

    paths = LivePaths(project_root=project_root)
    config = load_live_config(paths.config_path)
    symbols = list(config.symbols)
    if not symbols:
        print("error: no symbols in live config", file=sys.stderr)
        return 1

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"paper_account_reset mode={mode} symbols={symbols}")

    if args.wait_rth:
        print("waiting for US regular hours…")
        ts = wait_until_rth()
        print(f"RTH open at {ts.isoformat()}")
    elif args.execute and not is_us_equity_rth(datetime.now(timezone.utc)):
        print(
            "error: not regular hours; re-run with --wait-rth or during the cash session",
            file=sys.stderr,
        )
        return 2

    if not args.skip_timer:
        systemctl(["stop", "live-worker.timer"], dry_run=dry_run)
        # Stop any in-flight oneshot as well.
        systemctl(["stop", "live-worker.service"], dry_run=dry_run)

    port = int(os.environ.get("IB_PORT", "4002"))
    broker = IbkrBroker(dry_run=False, port=port)
    try:
        positions = broker.get_positions()
        snap = broker.get_account_snapshot()
        prices, _bars, _closes = broker.latest_hourly_closes(symbols, use_rth=True)
        # Fall back to last_price in state when hist missing.
        if paths.state_path.is_file():
            import json

            raw = json.loads(paths.state_path.read_text(encoding="utf-8"))
            for sym, row in (raw.get("assets") or {}).items():
                if sym not in prices and row.get("last_price") is not None:
                    try:
                        prices[sym] = float(row["last_price"])
                    except (TypeError, ValueError):
                        pass

        plan = plan_reset(
            symbols=symbols,
            positions=positions,
            prices=prices,
            equity=float(snap.equity_usd),
            available_funds=float(snap.spendable_usd),
        )
        print("plan:")
        print(f"  equity/total_cash={plan.total_cash:.2f}")
        print(f"  spendable(never-borrow)={plan.available_funds:.2f}")
        print(f"  broker_available_funds={float(snap.available_funds_usd or 0):.2f}")
        print(f"  cash={float(snap.cash_usd):.2f}")
        print(f"  sell={plan.positions_to_sell}")
        print(f"  sleeve_cash={{{', '.join(f'{k}: {v:.2f}' for k, v in plan.sleeve_cash.items())}}}")

        backup_dir = None
        if not dry_run:
            backup_dir = backup_live_files(paths, args.backup_root)
            print(f"backup={backup_dir}")

        cancel_open_orders(broker, dry_run=dry_run)
        flatten_longs(broker, plan.positions_to_sell, dry_run=dry_run)

        # Refresh cash after fills for accurate redistrib.
        if not dry_run:
            snap = broker.get_account_snapshot()
            equity = float(snap.equity_usd)
            # After flatten, spendable ≈ cash (same-day AF only if still flat).
            avail = float(snap.spendable_usd)
            left = {s: q for s, q in broker.get_positions().items() if q > 1e-9 and s in symbols}
            if left:
                raise RuntimeError(f"still long after flatten: {left}")
            sleeve = plan.sleeve_cash
            # Recompute from post-flatten never-borrow spendable + current prices.
            from app.live.paper_reset import redistribute_sleeve_cash

            if prices:
                sleeve = redistribute_sleeve_cash(symbols, prices, avail)
            apply_state_reset(
                paths,
                symbols=symbols,
                total_cash=equity,
                sleeve_cash=sleeve,
                use_account_cash=True,
            )
            print(
                f"state reset ok total_cash={equity:.2f} "
                f"spendable={avail:.2f} cash={float(snap.cash_usd):.2f}"
            )
            print(f"sleeve_cash={{{', '.join(f'{k}: {v:.2f}' for k, v in sleeve.items())}}}")
        else:
            print("dry-run: skipped flatten fills + state write")
    finally:
        ib = getattr(broker, "ib", None)
        if ib is not None and getattr(ib, "isConnected", lambda: False)():
            ib.disconnect()

    if not args.skip_timer:
        systemctl(["start", "live-worker.timer"], dry_run=dry_run)

    if not args.skip_worker_cycle and not dry_run:
        print("running one live_worker cycle…")
        rc = subprocess.call(
            [
                sys.executable,
                "-m",
                "app.live_worker",
                "--mode",
                "broker_paper",
                "--broker",
                "ibkr",
            ],
            cwd=str(project_root),
        )
        print(f"worker_rc={rc}")
        if rc != 0:
            return rc

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
