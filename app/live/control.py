"""Dashboard controls that only touch state_live files. No secrets."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.live.budget import (
    RebalancePlanResult,
    invested_usd,
    plan_rebalance_to_equal,
    plan_reduce_to_budget,
)
from app.live.config import load_live_config, save_live_config
from app.live.session import is_us_equity_rth, next_rth_open
from app.paths import LivePaths, PickerPaths
from app.picker.active import clear_awaiting_first_buy, load_active, save_active
from app.picker.trend_gate import allow_first_buy
from app.risk.escalate import RiskController

# Hard bounds for dashboard edits (paper soak + live safety).
DAILY_ORDER_CAP_MIN = 1
DAILY_ORDER_CAP_MAX = 50
TRADING_BUDGET_USD_MAX = 50_000_000.0


def _paths(paths: LivePaths | None) -> LivePaths:
    return paths or LivePaths()


def live_status(paths: LivePaths | None = None) -> dict:
    chosen = _paths(paths)
    status = {
        "mode": "live_dry_run",
        "symbols": [],
        "trading_enabled": False,
        "incident": None,
        "assets": {},
        "daily_order_cap": 5,
        "orders_today": 0,
        "orders_today_by_symbol": {},
    }
    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        status["mode"] = config.mode.value
        status["symbols"] = list(config.symbols)
        status["trading_enabled"] = config.trading_enabled
        status["daily_order_cap"] = int(config.daily_order_cap)
    if chosen.risk_path.exists():
        raw = json.loads(chosen.risk_path.read_text(encoding="utf-8"))
        status["trading_enabled"] = bool(raw.get("trading_enabled", status["trading_enabled"]))
        status["incident"] = raw.get("open_incident")
    if chosen.state_path.exists():
        state = json.loads(chosen.state_path.read_text(encoding="utf-8"))
        status["assets"] = state.get("assets", {})
        status["orders_today"] = int(state.get("orders_today") or 0)
        by_sym = state.get("orders_today_by_symbol")
        status["orders_today_by_symbol"] = dict(by_sym) if isinstance(by_sym, dict) else {}
    return status


def set_daily_order_cap(paths: LivePaths | None = None, cap: int = 5) -> int:
    """Persist a new per-symbol daily order cap. Returns the value written."""
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    value = int(cap)
    if value < DAILY_ORDER_CAP_MIN or value > DAILY_ORDER_CAP_MAX:
        raise ValueError(
            f"daily_order_cap must be between {DAILY_ORDER_CAP_MIN} and {DAILY_ORDER_CAP_MAX}"
        )
    if not chosen.config_path.exists():
        raise FileNotFoundError(f"missing live config: {chosen.config_path}")
    config = load_live_config(chosen.config_path)
    config.daily_order_cap = value
    save_live_config(chosen.config_path, config)
    return value


def set_trading_budget_usd(paths: LivePaths | None = None, budget_usd: float = 0.0) -> float:
    """Persist trading budget (USD wallet). Does not place orders."""
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    value = float(budget_usd)
    if value < 0 or value > TRADING_BUDGET_USD_MAX:
        raise ValueError(f"trading_budget_usd must be between 0 and {TRADING_BUDGET_USD_MAX:,.0f}")
    if not chosen.config_path.exists():
        raise FileNotFoundError(f"missing live config: {chosen.config_path}")
    config = load_live_config(chosen.config_path)
    config.trading_budget_usd = value
    save_live_config(chosen.config_path, config)
    # Echo onto state for dashboard without waiting for a worker cycle.
    if chosen.state_path.exists():
        raw = json.loads(chosen.state_path.read_text(encoding="utf-8"))
        raw["trading_budget_usd"] = value
        chosen.state_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return value


def bot_book_symbols(paths: LivePaths | None = None) -> list[str]:
    """Symbols the bot may touch: live config ∪ active_selection (incl. exit_only).

    Never expand to arbitrary IBKR longs — Reduce/rebalance must stay inside this set.
    """
    chosen = _paths(paths)
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        sym = str(raw or "").upper().strip()
        if not sym or sym in seen:
            return
        seen.add(sym)
        ordered.append(sym)

    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        for sym in config.symbols:
            _add(sym)
    picker_paths = PickerPaths(project_root=chosen.project_root)
    active = load_active(picker_paths.active_selection_path)
    if active is not None:
        for row in active.symbols:
            _add(row.symbol)
    return ordered


def scoped_bot_positions(
    paths: LivePaths | None,
    positions: Mapping[str, float],
) -> dict[str, float]:
    """Longs in ``positions`` that belong to the bot book (fail closed if book empty)."""
    book = {s.upper() for s in bot_book_symbols(paths)}
    if not book:
        return {}
    out: dict[str, float] = {}
    for key, qty in positions.items():
        sym = str(key).upper()
        if sym not in book:
            continue
        shares = float(qty or 0.0)
        if shares > 1e-9:
            out[sym] = shares
    return out


def preview_reduce_to_budget(
    *,
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    budget_usd: float,
    paths: LivePaths | None = None,
) -> list[dict[str, Any]]:
    """Dry-run reduce plan (no orders). Scopes to bot book when ``paths`` is set."""
    scoped = (
        scoped_bot_positions(paths, positions)
        if paths is not None
        else {str(k).upper(): float(v) for k, v in positions.items() if float(v or 0) > 1e-9}
    )
    sells = plan_reduce_to_budget(scoped, prices, budget_usd=float(budget_usd))
    return [
        {
            "symbol": s.symbol,
            "shares": s.shares,
            "price": s.price,
            "notional": round(s.notional, 2),
        }
        for s in sells
    ]


def _broker_prices(broker: Any, symbols: Sequence[str] | None = None) -> dict[str, float]:
    """Best-effort USD last prices from broker book + portfolio."""
    prices: dict[str, float] = {}
    price_book = getattr(broker, "last_prices", None) or {}
    for sym, px in price_book.items():
        try:
            prices[str(sym).upper()] = float(px)
        except (TypeError, ValueError):
            continue
    ib = getattr(broker, "ib", None)
    if ib is not None and hasattr(ib, "portfolio"):
        for p in ib.portfolio():
            sym = getattr(getattr(p, "contract", None), "symbol", None)
            if not sym:
                continue
            try:
                px = float(getattr(p, "marketPrice", 0) or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                prices.setdefault(str(sym).upper(), px)
    if symbols and hasattr(broker, "latest_hourly_closes"):
        try:
            px_map, _bars, _closes = broker.latest_hourly_closes(
                [str(s) for s in symbols], use_rth=True
            )
            for sym, px in (px_map or {}).items():
                try:
                    val = float(px)
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    prices.setdefault(str(sym).upper(), val)
        except Exception:  # noqa: BLE001
            pass
    return prices


def _sma20_ok_map(
    broker: Any,
    symbols: Sequence[str],
    prices: Mapping[str, float],
) -> dict[str, bool]:
    """True when price is strictly above 20-hour SMA (fail closed)."""
    closes_by: dict[str, list[float]] = {}
    if hasattr(broker, "latest_hourly_closes"):
        try:
            _px, _bars, closes = broker.latest_hourly_closes(
                [str(s) for s in symbols], use_rth=True
            )
            if isinstance(closes, dict):
                for sym, series in closes.items():
                    if isinstance(series, (list, tuple)):
                        closes_by[str(sym).upper()] = [float(x) for x in series]
        except Exception:  # noqa: BLE001
            closes_by = {}
    out: dict[str, bool] = {}
    for sym in symbols:
        key = str(sym).upper()
        history = closes_by.get(key) or []
        px = prices.get(key)
        out[key] = allow_first_buy(history, price=px)
    return out


def _exit_only_symbols(paths: LivePaths) -> set[str]:
    """Symbols currently marked exit_only in active_selection (soft-rotate drops)."""
    picker_paths = PickerPaths(project_root=paths.project_root)
    active = load_active(picker_paths.active_selection_path)
    if active is None:
        return set()
    return {str(row.symbol).upper() for row in active.symbols if row.exit_only}


def _exit_only_invested_usd(
    paths: LivePaths,
    positions: Mapping[str, float],
    prices: Mapping[str, float],
) -> float:
    """USD mark of exit-only longs still held (counts against the wallet)."""
    exit_syms = _exit_only_symbols(paths)
    if not exit_syms:
        return 0.0
    subset = {
        sym: float(positions.get(sym, 0.0) or 0.0)
        for sym in exit_syms
    }
    return invested_usd(subset, prices)


def _order_row(o: Any) -> dict[str, Any]:
    return {
        "symbol": o.symbol,
        "side": o.side,
        "shares": o.shares,
        "price": o.price,
        "notional": round(float(o.notional), 2),
        "target_usd": round(float(o.target_usd), 2),
        "current_usd": round(float(o.current_usd), 2),
    }


def _skip_row(s: Any) -> dict[str, Any]:
    return {
        "symbol": s.symbol,
        "reason": s.reason,
        "target_usd": round(float(s.target_usd), 2),
        "current_usd": round(float(s.current_usd), 2),
        "price": None if s.price is None else round(float(s.price), 4),
    }


def preview_rebalance_to_equal(
    *,
    symbols: Sequence[str],
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    budget_usd: float,
    spendable_usd: float,
    sma20_ok: Mapping[str, bool] | None = None,
    exit_only_invested_usd: float = 0.0,
) -> dict[str, Any]:
    """Dry-run equal-sleeve rebalance (no orders)."""
    plan = plan_rebalance_to_equal(
        symbols,
        positions,
        prices,
        budget_usd=float(budget_usd),
        spendable_usd=float(spendable_usd),
        sma20_ok=sma20_ok,
        exit_only_invested_usd=float(exit_only_invested_usd),
    )
    return _rebalance_summary(plan, dry_run=True, budget_usd=float(budget_usd))


def preview_rebalance_from_broker(
    broker: Any,
    *,
    symbols: Sequence[str],
    budget_usd: float,
    spendable_usd: float | None = None,
    fallback_prices: Mapping[str, float] | None = None,
    paths: LivePaths | None = None,
) -> dict[str, Any]:
    """Build SMA20-aware rebalance preview from a live broker connection."""
    chosen = _paths(paths)
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    positions = {str(k).upper(): float(v) for k, v in (broker.get_positions() or {}).items()}
    for sym in syms:
        positions.setdefault(sym, 0.0)
    exit_syms = _exit_only_symbols(chosen)
    price_syms = list(dict.fromkeys([*syms, *sorted(exit_syms)]))
    prices = _broker_prices(broker, price_syms)
    for sym, px in (fallback_prices or {}).items():
        key = str(sym).upper()
        try:
            val = float(px)
        except (TypeError, ValueError):
            continue
        if key not in prices and val > 0:
            prices[key] = val
    sma_ok = _sma20_ok_map(broker, syms, prices)
    if spendable_usd is None:
        snap = broker.get_account_snapshot()
        spendable = float(getattr(snap, "spendable_usd", 0.0) or 0.0)
    else:
        spendable = float(spendable_usd)
    exit_only_inv = _exit_only_invested_usd(chosen, positions, prices)
    return preview_rebalance_to_equal(
        symbols=syms,
        positions=positions,
        prices=prices,
        budget_usd=float(budget_usd),
        spendable_usd=spendable,
        sma20_ok=sma_ok,
        exit_only_invested_usd=exit_only_inv,
    )


def _rebalance_summary(
    plan: RebalancePlanResult,
    *,
    dry_run: bool,
    budget_usd: float,
    executed: bool = False,
) -> dict[str, Any]:
    sells = [_order_row(o) for o in plan.sells]
    buys = [_order_row(o) for o in plan.buys]
    return {
        "dry_run": dry_run,
        "executed": executed,
        "budget_usd": float(budget_usd),
        "deployable_budget_usd": round(float(plan.deployable_budget_usd), 2),
        "exit_only_invested_usd": round(float(plan.exit_only_invested_usd), 2),
        "target_per_sleeve": round(float(plan.target_per_sleeve), 2),
        "n_symbols": int(plan.n_symbols),
        "sells": sells,
        "buys": buys,
        "skipped": [_skip_row(s) for s in plan.skipped],
        "sell_notional": round(sum(float(s["notional"]) for s in sells), 2),
        "buy_notional": round(sum(float(b["notional"]) for b in buys), 2),
        "orders": sells + buys,
    }


def _require_trading_enabled(paths: LivePaths) -> None:
    status = live_status(paths)
    if not status.get("trading_enabled"):
        raise RuntimeError("Trading is disabled — enable under Safety before rebalance.")


def _require_rth(now: datetime | None = None) -> None:
    ts = now or datetime.now(timezone.utc)
    if is_us_equity_rth(ts):
        return
    nxt = next_rth_open(ts)
    raise RuntimeError(
        f"Not US regular hours — rebalance refused. Next RTH open ≈ {nxt.isoformat()}"
    )


def _pause_live_worker(*, dry_run: bool) -> None:
    from app.live.paper_reset import systemctl

    systemctl(["stop", "live-worker.timer"], dry_run=dry_run)
    systemctl(["stop", "live-worker.service"], dry_run=dry_run)


def _resume_live_worker(*, dry_run: bool) -> None:
    from app.live.paper_reset import systemctl

    systemctl(["start", "live-worker.timer"], dry_run=dry_run)


def _sync_state_after_rebalance(
    paths: LivePaths,
    *,
    budget_usd: float,
    broker: Any,
    prices: Mapping[str, float],
    bought: Sequence[str],
    sold: Sequence[str],
) -> None:
    """Align sleeve shares/peak/trough/flags with broker after dashboard rebalance."""
    positions = {str(k).upper(): float(v) for k, v in broker.get_positions().items()}
    touched = {str(s).upper() for s in list(bought) + list(sold)}
    if paths.state_path.exists():
        raw = json.loads(paths.state_path.read_text(encoding="utf-8"))
    else:
        raw = {"assets": {}}
    assets = raw.setdefault("assets", {})
    if not isinstance(assets, dict):
        assets = {}
        raw["assets"] = assets
    raw["trading_budget_usd"] = float(budget_usd)

    for sym in touched:
        row = dict(assets.get(sym) or {})
        sh = float(positions.get(sym, 0.0) or 0.0)
        px = float(prices.get(sym) or row.get("last_price") or 0.0)
        row["shares"] = max(0.0, sh)
        if px > 0:
            row["last_price"] = px
        if sh <= 1e-9:
            row["peak"] = None
            row["exit_pending"] = False
            # Keep trough for re-entry tracking if present.
        else:
            row["exit_pending"] = False
            if sym in {str(s).upper() for s in bought}:
                row["peak"] = px if px > 0 else row.get("peak")
                row["trough"] = px if px > 0 else row.get("trough")
            # Partial sell: keep peak for trail.
        assets[sym] = row

    # Also refresh shares for any listed asset from broker (reconcile).
    for sym, sh in positions.items():
        if sym in assets:
            assets[sym]["shares"] = max(0.0, float(sh))

    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    picker_paths = PickerPaths(project_root=paths.project_root)
    active = load_active(picker_paths.active_selection_path)
    if active is not None:
        dirty = False
        for sym in bought:
            if clear_awaiting_first_buy(active, str(sym).upper()):
                dirty = True
        if dirty:
            save_active(picker_paths.active_selection_path, active)


def execute_rebalance_to_equal(
    broker: Any,
    *,
    symbols: Sequence[str],
    budget_usd: float,
    dry_run: bool = True,
    paths: LivePaths | None = None,
    pause_worker: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Equal-sleeve rebalance: SELL overweight, BUY underweight (SMA20-gated).

    Stops live-worker for the duration when ``pause_worker`` and not dry_run.
    """
    chosen = _paths(paths)
    _require_trading_enabled(chosen)
    if not dry_run:
        _require_rth(now)

    syms = [str(s).upper() for s in symbols if str(s).strip()]
    if not syms:
        raise ValueError("no symbols to rebalance")

    worker_paused = False
    if pause_worker and not dry_run:
        _pause_live_worker(dry_run=False)
        worker_paused = True

    try:
        set_trading_budget_usd(chosen, float(budget_usd))
        positions = {
            str(k).upper(): float(v) for k, v in (broker.get_positions() or {}).items()
        }
        exit_syms = _exit_only_symbols(chosen)
        price_syms = list(dict.fromkeys([*syms, *sorted(exit_syms)]))
        prices = _broker_prices(broker, price_syms)
        # State last_price fallback.
        if chosen.state_path.exists():
            raw = json.loads(chosen.state_path.read_text(encoding="utf-8"))
            for sym, row in (raw.get("assets") or {}).items():
                key = str(sym).upper()
                if key in prices:
                    continue
                try:
                    px = float(row.get("last_price"))
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    prices[key] = px

        sma_ok = _sma20_ok_map(broker, syms, prices)
        snap = broker.get_account_snapshot()
        spendable = float(getattr(snap, "spendable_usd", 0.0) or 0.0)
        exit_only_inv = _exit_only_invested_usd(chosen, positions, prices)

        plan = plan_rebalance_to_equal(
            syms,
            positions,
            prices,
            budget_usd=float(budget_usd),
            spendable_usd=spendable,
            sma20_ok=sma_ok,
            exit_only_invested_usd=exit_only_inv,
        )
        summary = _rebalance_summary(plan, dry_run=dry_run, budget_usd=float(budget_usd))
        if dry_run or not plan.orders:
            return summary

        ib = getattr(broker, "ib", None)
        sold_syms: list[str] = []
        for o in plan.sells:
            result = broker.place_market_order(o.symbol, "SELL", o.shares)
            print(
                f"rebalance: SELL {o.symbol} x {o.shares} -> {getattr(result, 'status', result)}"
            )
            sold_syms.append(o.symbol)
            if ib is not None and hasattr(ib, "sleep"):
                ib.sleep(1)

        # Wait briefly for sell proceeds / position update.
        if plan.sells:
            deadline = time.time() + 90.0
            while time.time() < deadline:
                if ib is not None and hasattr(ib, "sleep"):
                    ib.sleep(2)
                else:
                    time.sleep(2)
                live = {
                    str(k).upper(): float(v)
                    for k, v in (broker.get_positions() or {}).items()
                }
                done = True
                for o in plan.sells:
                    before = float(positions.get(o.symbol, 0.0) or 0.0)
                    now_sh = float(live.get(o.symbol, 0.0) or 0.0)
                    if now_sh > before - float(o.shares) + 0.5:
                        done = False
                        break
                if done:
                    break

        snap = broker.get_account_snapshot()
        spendable_after = float(getattr(snap, "spendable_usd", 0.0) or 0.0)
        live_pos = {
            str(k).upper(): float(v) for k, v in (broker.get_positions() or {}).items()
        }
        # Recompute exit-only mark after sells (drops may have sold via other path;
        # rebalance itself never sells exit_only).
        exit_only_inv_after = _exit_only_invested_usd(chosen, live_pos, prices)
        # Rebuild buys only with post-sell cash (no double-count sell proceeds).
        plan_buys = plan_rebalance_to_equal(
            syms,
            live_pos,
            prices,
            budget_usd=float(budget_usd),
            spendable_usd=spendable_after,
            sma20_ok=sma_ok,
            exit_only_invested_usd=exit_only_inv_after,
        )
        bought_syms: list[str] = []
        for o in plan_buys.buys:
            result = broker.place_market_order(o.symbol, "BUY", o.shares)
            print(
                f"rebalance: BUY {o.symbol} x {o.shares} -> {getattr(result, 'status', result)}"
            )
            bought_syms.append(o.symbol)
            if ib is not None and hasattr(ib, "sleep"):
                ib.sleep(1)

        if ib is not None and hasattr(ib, "sleep"):
            ib.sleep(2)

        _sync_state_after_rebalance(
            chosen,
            budget_usd=float(budget_usd),
            broker=broker,
            prices=prices,
            bought=bought_syms,
            sold=sold_syms,
        )
        # Refresh summary with actual buy legs submitted.
        final_orders = list(plan.sells) + list(plan_buys.buys)
        final_plan = RebalancePlanResult(
            orders=final_orders,
            skipped=list(plan.skipped) + [
                s for s in plan_buys.skipped if s.reason == "cash_clamp"
            ],
            target_per_sleeve=plan_buys.target_per_sleeve,
            n_symbols=plan.n_symbols,
            deployable_budget_usd=plan_buys.deployable_budget_usd,
            exit_only_invested_usd=plan_buys.exit_only_invested_usd,
        )
        out = _rebalance_summary(
            final_plan, dry_run=False, budget_usd=float(budget_usd), executed=True
        )
        return out
    finally:
        if worker_paused:
            try:
                _resume_live_worker(dry_run=False)
            except Exception as exc:  # noqa: BLE001
                print(f"rebalance: failed to restart live-worker.timer: {exc}")


def execute_reduce_to_budget(
    broker: Any,
    *,
    budget_usd: float,
    dry_run: bool = True,
    paths: LivePaths | None = None,
    pause_worker: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Market-sell bot-book longs down to ``budget_usd`` invested.

    Scopes to live config ∪ active_selection only (never unmanaged IBKR longs).
    Requires trading enabled + US RTH when not dry-run; pauses live-worker like rebalance.
    Does not change ``trading_budget_usd`` (caller should already have set it).
    """
    from app.live.paper_reset import flatten_longs

    chosen = _paths(paths)
    book = bot_book_symbols(chosen)
    if not book:
        raise ValueError("no bot-book symbols — refusing Reduce (fail closed)")
    _require_trading_enabled(chosen)
    if not dry_run:
        _require_rth(now)

    worker_paused = False
    if pause_worker and not dry_run:
        _pause_live_worker(dry_run=False)
        worker_paused = True

    try:
        raw_positions = {
            str(k).upper(): float(v) for k, v in (broker.get_positions() or {}).items()
        }
        positions = scoped_bot_positions(chosen, raw_positions)
        prices = _broker_prices(broker, list(dict.fromkeys([*book, *positions])))
        # State last_price fallback for marks.
        if chosen.state_path.exists():
            raw = json.loads(chosen.state_path.read_text(encoding="utf-8"))
            for sym, row in (raw.get("assets") or {}).items():
                key = str(sym).upper()
                if key in prices:
                    continue
                try:
                    px = float(row.get("last_price"))
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    prices[key] = px

        plan = plan_reduce_to_budget(positions, prices, budget_usd=float(budget_usd))
        summary: dict[str, Any] = {
            "dry_run": dry_run,
            "budget_usd": float(budget_usd),
            "bot_book": book,
            "sells": [
                {
                    "symbol": s.symbol,
                    "shares": s.shares,
                    "price": s.price,
                    "notional": s.notional,
                }
                for s in plan
            ],
            "notional": round(sum(s.notional for s in plan), 2),
        }
        if dry_run or not plan:
            return summary

        ib = getattr(broker, "ib", None)
        for s in plan:
            result = broker.place_market_order(s.symbol, "SELL", s.shares)
            print(
                f"reduce: SELL {s.symbol} x {s.shares} -> {getattr(result, 'status', result)}"
            )
            if ib is not None and hasattr(ib, "sleep"):
                ib.sleep(1)

        if float(budget_usd) <= 1e-9:
            # Urgent full exit of bot book only — never flatten unmanaged longs.
            left = scoped_bot_positions(chosen, broker.get_positions() or {})
            if left:
                flatten_longs(broker, left, dry_run=False)
        elif ib is not None and hasattr(ib, "sleep"):
            ib.sleep(3)

        summary["executed"] = True
        if chosen.state_path.exists():
            raw = json.loads(chosen.state_path.read_text(encoding="utf-8"))
            raw["trading_budget_usd"] = float(budget_usd)
            live_pos = {
                str(k).upper(): float(v)
                for k, v in (broker.get_positions() or {}).items()
            }
            assets = raw.setdefault("assets", {})
            if isinstance(assets, dict):
                for sym in book:
                    if sym in assets:
                        assets[sym]["shares"] = max(0.0, float(live_pos.get(sym, 0.0) or 0.0))
            chosen.state_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        return summary
    finally:
        if worker_paused:
            try:
                _resume_live_worker(dry_run=False)
            except Exception as exc:  # noqa: BLE001
                print(f"reduce: failed to restart live-worker.timer: {exc}")


def disable_trading(paths: LivePaths | None = None) -> None:
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    RiskController(chosen.risk_path).disable()
    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        config.trading_enabled = False
        save_live_config(chosen.config_path, config)


def enable_trading(paths: LivePaths | None = None) -> None:
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    RiskController(chosen.risk_path).enable()
    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        config.trading_enabled = True
        save_live_config(chosen.config_path, config)


def ack_risk(paths: LivePaths | None = None, now: datetime | None = None) -> None:
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    RiskController(chosen.risk_path).ack(now or datetime.now(timezone.utc))
