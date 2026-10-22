"""One-time paper flatten + whole-account sleeve redistrib (ops helper).

Keeps current live symbols. Does not touch state/ or state_v2/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.live.config import LiveConfig, load_live_config, save_live_config
from app.live.queue import PendingIntentStore
from app.live.session import is_us_equity_rth, next_rth_open
from app.paths import LivePaths
from app.picker.sizing import allocate_priority_sleeves


@dataclass(frozen=True)
class ResetPlan:
    symbols: list[str]
    positions_to_sell: dict[str, float]
    total_cash: float
    available_funds: float
    sleeve_cash: dict[str, float]
    backup_dir: Path | None = None


def backup_live_files(paths: LivePaths, backup_root: Path) -> Path:
    """Copy config/state/last_cycle/queue into a timestamped backup dir."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(backup_root) / f"ovh-reset-bak-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "state.json", "last_cycle.json", "queue.json"):
        src = paths.state_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    return dest


def build_flat_assets(
    symbols: Sequence[str],
    sleeve_cash: Mapping[str, float],
    *,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Zero shares/peaks/troughs; assign redistributed cash per sleeve."""
    out: dict[str, dict[str, Any]] = {}
    prev = existing or {}
    for sym in symbols:
        prior = dict(prev.get(sym) or {})
        out[sym] = {
            "cash": float(sleeve_cash.get(sym, 0.0)),
            "shares": 0.0,
            "peak": None,
            "trough": None,
            "last_price": prior.get("last_price"),
        }
    return out


def redistribute_sleeve_cash(
    symbols: Sequence[str],
    prices: Mapping[str, float],
    available_funds: float,
) -> dict[str, float]:
    """Priority whole-share budgets across all symbols; equal split if no prices."""
    syms = [str(s).strip() for s in symbols if str(s).strip()]
    if not syms:
        return {}
    pool = max(0.0, float(available_funds))
    priced = {s: float(prices[s]) for s in syms if s in prices and float(prices[s]) > 0}
    if len(priced) == len(syms):
        allocs = allocate_priority_sleeves(syms, priced, pool, max_n=len(syms))
        cash = {a.symbol: float(a.cash) for a in allocs}
        # Any symbol skipped (should not happen when all priced) gets 0.
        for s in syms:
            cash.setdefault(s, 0.0)
        return cash
    each = pool / float(len(syms))
    return {s: each for s in syms}


def apply_state_reset(
    paths: LivePaths,
    *,
    symbols: Sequence[str],
    total_cash: float,
    sleeve_cash: Mapping[str, float],
    use_account_cash: bool = True,
) -> LiveConfig:
    """Rewrite live config + flat state; clear order queue."""
    config = load_live_config(paths.config_path)
    config.symbols = list(symbols)
    config.total_cash = float(total_cash)
    config.use_account_cash = bool(use_account_cash)
    # Keep SymbolParams entries aligned with symbols.
    by_sym = {a.symbol: a for a in config.assets}
    from app.live.config import SymbolParams

    config.assets = [by_sym.get(s) or SymbolParams(symbol=s) for s in config.symbols]
    save_live_config(paths.config_path, config)

    raw: dict[str, Any] = {}
    if paths.state_path.is_file():
        raw = json.loads(paths.state_path.read_text(encoding="utf-8"))
    assets = build_flat_assets(config.symbols, sleeve_cash, existing=raw.get("assets") or {})
    raw["assets"] = assets
    raw["cash_usd"] = float(total_cash)
    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    PendingIntentStore(paths.queue_path).clear()
    return config


def longs_to_sell(positions: Mapping[str, float], symbols: Sequence[str]) -> dict[str, float]:
    """Positive broker qty for symbols in the live book."""
    want = {str(s) for s in symbols}
    out: dict[str, float] = {}
    for sym, qty in positions.items():
        q = float(qty)
        if sym in want and q > 1e-9:
            out[sym] = q
    return out


def wait_until_rth(*, now_fn: Callable[[], datetime] | None = None, sleep_fn=time.sleep) -> datetime:
    """Block until US equity regular hours (poll every 30s)."""
    now = now_fn or (lambda: datetime.now(timezone.utc))
    while True:
        ts = now()
        if is_us_equity_rth(ts):
            return ts
        nxt = next_rth_open(ts)
        # Sleep until open, but wake every 30s so clock skew / early open is fine.
        delay = min(30.0, max(1.0, (nxt - ts).total_seconds()))
        sleep_fn(delay)


def systemctl(args: Sequence[str], *, dry_run: bool) -> None:
    cmd = ["sudo", "systemctl", *args]
    print("systemctl:", " ".join(cmd), "(dry_run)" if dry_run else "")
    if dry_run:
        return
    subprocess.check_call(cmd)


def flatten_longs(
    broker: Any,
    to_sell: Mapping[str, float],
    *,
    dry_run: bool,
    timeout_sec: float = 180.0,
    sleep_fn=time.sleep,
) -> None:
    """Market-sell each long and poll until those symbols are flat."""
    if not to_sell:
        print("flatten: nothing to sell")
        return
    for sym, qty in to_sell.items():
        q = float(qty)
        print(f"flatten: SELL {sym} x {q}")
        if dry_run:
            continue
        result = broker.place_market_order(sym, "SELL", q)
        print(f"  order {result.order_id} status={result.status}")
        ib = getattr(broker, "ib", None)
        if ib is not None and hasattr(ib, "sleep"):
            ib.sleep(1)

    if dry_run:
        return

    deadline = time.time() + float(timeout_sec)
    symbols = list(to_sell)
    while time.time() < deadline:
        ib = getattr(broker, "ib", None)
        if ib is not None and hasattr(ib, "sleep"):
            ib.sleep(1)
        else:
            sleep_fn(1)
        pos = broker.get_positions()
        left = longs_to_sell(pos, symbols)
        if not left:
            print("flatten: all flat")
            return
        print(f"flatten: waiting on {left}")
    raise RuntimeError(f"flatten timeout; still long: {longs_to_sell(broker.get_positions(), symbols)}")


def cancel_open_orders(broker: Any, *, dry_run: bool) -> None:
    ib = getattr(broker, "ib", None)
    if ib is None or not hasattr(ib, "openTrades"):
        return
    trades = list(ib.openTrades())
    print(f"cancel_open_orders: n={len(trades)}")
    if dry_run:
        return
    for trade in trades:
        try:
            ib.cancelOrder(trade.order)
        except Exception as exc:  # noqa: BLE001
            print(f"  cancel failed: {exc}")
    if hasattr(ib, "sleep"):
        ib.sleep(1)


def plan_reset(
    *,
    symbols: Sequence[str],
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    equity: float,
    available_funds: float,
) -> ResetPlan:
    sells = longs_to_sell(positions, symbols)
    # Pre-flatten dry-run: estimate post-cash pool from equity (cash returns on sells).
    pool = max(float(equity), float(available_funds))
    sleeve = redistribute_sleeve_cash(symbols, prices, pool)
    return ResetPlan(
        symbols=list(symbols),
        positions_to_sell=sells,
        total_cash=float(equity),
        available_funds=float(available_funds),
        sleeve_cash=sleeve,
    )
