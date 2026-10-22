"""Live-variant cycle.

Usage:
    python -m app.live_worker --mode broker_paper --broker ibkr
    python -m app.live_worker --mode live_dry_run --broker memory
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.audit.log import AuditLog
from app.broker.memory import InMemoryBroker
from app.fees import default_ibkr_us_stock_schedule
from app.broker.gateway import BrokerGateway
from app.live.config import bootstrap_live_state, load_live_config, save_live_config
from app.live.executor import execute_intent
from app.notifier import clear_alert_cooldown, notify_live_event
from app.live.idempotency import IdempotencyStore
from app.live.modes import TradingMode, parse_mode
from app.live.planner import plan_from_signal
from app.live.queue import PendingIntentStore
from app.live.reconcile import LocalSleeveState, reconcile
from app.live.session import is_us_equity_rth
from app.paths import LivePaths, PickerPaths, StatePaths
from app.picker.active import (
    clear_awaiting_first_buy,
    clear_exit_only_if_flat,
    load_active,
    save_active,
)
from app.picker.apply import maybe_apply_pending
from app.picker.sizing import sleeve_buy_budget
from app.picker.trend_gate import allow_first_buy, sma
from app.risk.escalate import RiskController
from app.strategy import StrategyState, portfolio_value, step_signal


def _fmt_usd(value: float) -> str:
    return f"${float(value):,.2f}"


def _first_buy_gate_reason(price: float, history: list[float]) -> str:
    avg = sma(history, window=20)
    if avg is None:
        return (
            "First buy waiting: need 20 hourly closes to check the average "
            f"(have {len(history)})"
        )
    return (
        f"First buy waiting: price {_fmt_usd(price)} is below "
        f"20-hour average {_fmt_usd(avg)}"
    )


def _zero_buy_qty_reason(*, price: float, cash: float) -> str:
    return (
        f"Buy signal, but cash {_fmt_usd(cash)} can't buy 1 share at {_fmt_usd(price)} "
        f"(need at least {_fmt_usd(price)})"
    )


def _humanize_signal_reason(
    signal: str | None,
    *,
    price: float,
    trough_before: float | None,
    peak_before: float | None,
    fallback: str,
) -> str:
    if signal == "BUY" and trough_before is not None:
        return (
            f"Buy signal: price {_fmt_usd(price)} bounced from recent low "
            f"{_fmt_usd(trough_before)}"
        )
    if signal == "SELL" and peak_before is not None:
        return (
            f"Sell signal: price {_fmt_usd(price)} dropped from recent high "
            f"{_fmt_usd(peak_before)}"
        )
    return fallback


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"assets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _append_equity(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Datetime", "symbol", "Price", "Portfolio_Value"])
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def run_live_once(
    paths: LivePaths,
    broker,
    risk: RiskController,
    audit: AuditLog,
    now_utc: datetime,
    price_by_symbol: dict[str, float],
    bar_ts_by_symbol: dict[str, str],
    closes_by_symbol: dict[str, list[float]] | None = None,
) -> dict:
    bootstrap_live_state(paths.state_dir)
    config = load_live_config(paths.config_path)
    broker = broker if isinstance(broker, BrokerGateway) else BrokerGateway(broker, config.mode)
    stopped_now = risk.tick(now_utc)
    if stopped_now:
        _safe_notify(
            "trading_stopped",
            "\n".join(
                [
                    "Trading was auto-stopped",
                    "",
                    "What happened",
                    "  A risk alert sat unacknowledged for 2 hours.",
                    "  The live worker will not place new orders until you re-enable trading.",
                    "",
                    "What to do",
                    "  Ack the incident on the dashboard (or risk control), then re-enable trading.",
                ]
            ),
            config.alerts,
        )
    if not risk.trading_enabled or not config.trading_enabled:
        return {"skipped": "trading_disabled"}

    picker_paths = PickerPaths(project_root=paths.project_root)
    rth_ok = is_us_equity_rth(now_utc)
    apply_result = maybe_apply_pending(
        picker_paths,
        paths,
        StatePaths(version="v1", project_root=paths.project_root),
        StatePaths(version="v2", project_root=paths.project_root),
        now_utc,
        rth_ok=rth_ok,
    )
    if apply_result.applied:
        _safe_notify(
            "picker_applied",
            "\n".join(
                [
                    "New picker sleeves are now live",
                    "",
                    "What this means",
                    "  Weekend ranking was applied to live + paper books.",
                    "  Soft-rotate rules are in effect (exit-only drops, awaiting first buy).",
                    "",
                    "Details",
                    f"  Run id: {apply_result.run_id}",
                ]
            ),
            config.alerts,
        )
        config = load_live_config(paths.config_path)
    elif apply_result.reason.startswith("stale_pending"):
        _safe_notify(
            "picker_stale",
            "\n".join(
                [
                    "Pending picker selection was NOT applied",
                    "",
                    "What this means",
                    "  The queued weekend ranking is past its apply window.",
                    "  Current sleeves stay unchanged until the next successful ranking.",
                    "",
                    "Details",
                    f"  Reason: {apply_result.reason}",
                    f"  Run id: {apply_result.run_id}",
                ]
            ),
            config.alerts,
        )

    active = load_active(picker_paths.active_selection_path)
    active_flags = {row.symbol: row for row in (active.symbols if active else [])}
    closes_by_symbol = closes_by_symbol or {}

    raw = _load_state(paths.state_path)
    assets = raw.setdefault("assets", {})
    local = LocalSleeveState(
        cash=float(raw.get("cash_usd", config.total_cash)),
        shares={symbol: float(assets.get(symbol, {}).get("shares", 0.0)) for symbol in config.symbols},
    )
    report = reconcile(local, broker)
    raw["cash_usd"] = report.corrected.cash

    fee_schedule = default_ibkr_us_stock_schedule()
    snapshot = broker.get_account_snapshot()
    actions: list[str] = []
    decisions: list[dict] = []
    idem = IdempotencyStore(paths.idempotency_path)
    queue = PendingIntentStore(paths.queue_path)
    active_dirty = False

    n_active = sum(1 for row in (active.symbols if active else []) if not row.exit_only) or len(
        [a for a in config.assets if a.enabled]
    )
    n_long = sum(
        1
        for symbol in config.symbols
        if float(report.corrected.shares.get(symbol, assets.get(symbol, {}).get("shares", 0.0))) > 0
        and not (active_flags.get(symbol) and active_flags[symbol].exit_only)
    )

    for asset in config.assets:
        symbol = asset.symbol
        if not asset.enabled or symbol not in price_by_symbol:
            continue
        price = float(price_by_symbol[symbol])
        price_book = getattr(broker, "inner", broker)
        if hasattr(price_book, "last_prices"):
            price_book.last_prices[symbol] = price
        stored = assets.get(
            symbol,
            {"cash": config.total_cash / max(len(config.symbols), 1), "shares": 0.0, "peak": None, "trough": None},
        )
        broker_shares = float(report.corrected.shares.get(symbol, stored.get("shares", 0.0)))
        before = StrategyState(
            cash=float(stored.get("cash", 0.0)),
            shares=broker_shares,
            peak=None if stored.get("peak") is None else float(stored["peak"]),
            trough=None if stored.get("trough") is None else float(stored["trough"]),
        )
        probe = StrategyState(cash=before.cash, shares=before.shares, peak=before.peak, trough=before.trough)
        trough_before = None if before.trough is None else float(before.trough)
        peak_before = None if before.peak is None else float(before.peak)
        signal, signal_reason = step_signal(
            probe,
            price,
            asset.buy_rise_pct / 100.0,
            asset.sell_drop_pct / 100.0,
        )
        signal_reason = _humanize_signal_reason(
            signal,
            price=price,
            trough_before=trough_before,
            peak_before=peak_before,
            fallback=signal_reason,
        )
        flags = active_flags.get(symbol)
        gate_reason = None
        if signal == "BUY" and flags is not None and flags.exit_only:
            signal = None
            gate_reason = "exit_only"
            signal_reason = "Dropped from picker — sells only; buys blocked"
        elif signal == "BUY" and flags is not None and flags.awaiting_first_buy:
            history = closes_by_symbol.get(symbol) or []
            if not allow_first_buy(history, price=price):
                signal = None
                gate_reason = "sma20_gate"
                signal_reason = _first_buy_gate_reason(price, history)
        if gate_reason is not None:
            # Discard probe fill; keep cash sleeve and update trough only.
            trough = before.trough
            if before.shares <= 0:
                trough = price if trough is None else min(float(trough), price)
            probe = StrategyState(
                cash=before.cash,
                shares=before.shares,
                peak=before.peak,
                trough=trough,
            )

        buy_cap = None
        if signal == "BUY":
            if config.use_account_cash:
                # Real funded-account mode: split whatever cash IBKR still has
                # among sleeves that are flat. AvailableFunds shrinks as you buy,
                # so this does not double-count the book.
                pool = max(0.0, float(snapshot.available_funds_usd or snapshot.spendable_usd or 0.0))
                buy_cap = sleeve_buy_budget(pool, n_active, n_long)
            else:
                # Fixed paper book: only this sleeve's assigned cash.
                sleeve_cash = max(0.0, float(before.cash))
                buy_cap = sleeve_cash if sleeve_cash > 0 else None
                if buy_cap is None:
                    book = min(float(snapshot.spendable_usd), float(config.total_cash))
                    buy_cap = sleeve_buy_budget(book, n_active, n_long)

        intent, plan_why = plan_from_signal(
            symbol,
            signal,
            before,
            price,
            config.allow_fractional_default and broker.supports_fractional(symbol),
            snapshot,
            fee_schedule,
            bar_ts_by_symbol.get(symbol, now_utc.isoformat()),
            buy_cash_cap=buy_cap,
        )
        if gate_reason and intent is None and plan_why == "no signal":
            if gate_reason == "sma20_gate":
                plan_why = "waiting on 20-hour average"
            elif gate_reason == "exit_only":
                plan_why = "sells only"
            else:
                plan_why = gate_reason
        if signal == "BUY" and plan_why == "zero quantity":
            cash_for_msg = float(buy_cap) if buy_cap is not None else float(before.cash)
            signal_reason = _zero_buy_qty_reason(price=price, cash=cash_for_msg)
            plan_why = "can't afford 1 share"
        filled = False
        exec_status = None
        if intent is not None:
            result = execute_intent(
                intent,
                broker,
                idem,
                audit,
                config.mode,
                rth_ok,
                queue,
            )
            exec_status = result.status
            actions.append(f"{symbol}:{result.status}")
            raw["orders_today"] = int(raw.get("orders_today", 0)) + (1 if result.status in {"filled", "partial", "submitted"} else 0)
            if result.status == "rejected":
                raw["reject_streak"] = int(raw.get("reject_streak", 0)) + 1
            else:
                raw["reject_streak"] = 0
            if raw["reject_streak"] >= 3:
                risk.trigger("reject_storm", now_utc)
                _safe_notify(
                    "risk_alert",
                    "\n".join(
                        [
                            "Repeated order rejects",
                            "",
                            "What happened",
                            "  Three rejects in a row — risk incident opened.",
                            "  Trading will auto-stop in 2 hours if you do not acknowledge.",
                            "",
                            f"Latest: {symbol} {intent.side}",
                        ]
                    ),
                    config.alerts,
                )
            if raw["orders_today"] > 6:
                risk.trigger("max_orders", now_utc)
                _safe_notify(
                    "risk_alert",
                    "\n".join(
                        [
                            "Daily order cap hit",
                            "",
                            "What happened",
                            f"  Orders today: {raw['orders_today']} (cap is 6).",
                            "  Risk incident opened — ack within 2 hours or trading auto-stops.",
                        ]
                    ),
                    config.alerts,
                )
            if result.status == "filled":
                qty = intent.quantity
                qty_txt = f"{qty:g}" if float(qty) == int(qty) else f"{qty:.4f}"
                _safe_notify(
                    "fill",
                    "\n".join(
                        [
                            f"{intent.side} {symbol} filled — {qty_txt} share(s)",
                            "",
                            "Details",
                            f"  Symbol:   {symbol}",
                            f"  Side:     {intent.side}",
                            f"  Quantity: {qty_txt}",
                            f"  Mode:     {config.mode.value}",
                            f"  Price ~   {price:.2f}",
                        ]
                    ),
                    config.alerts,
                )
            elif result.status == "rejected":
                _safe_notify(
                    "reject",
                    "\n".join(
                        [
                            f"{intent.side} {symbol} was rejected",
                            "",
                            "What this means",
                            "  The broker did not accept the order.",
                            "  No shares changed for this attempt.",
                            "",
                            "Details",
                            f"  Symbol:   {symbol}",
                            f"  Side:     {intent.side}",
                            f"  Quantity: {intent.quantity}",
                            f"  Mode:     {config.mode.value}",
                            f"  Price ~   {price:.2f}",
                        ]
                    ),
                    config.alerts,
                )
            filled = result.status == "filled"
            snapshot = broker.get_account_snapshot()
        saved = probe if (signal is None or filled) else before
        if filled:
            saved.shares = float(broker.get_positions().get(symbol, saved.shares))
            saved.cash = 0.0 if saved.shares > 0 and signal == "BUY" else snapshot.cash_usd
            if active is not None and signal == "BUY" and clear_awaiting_first_buy(active, symbol):
                active_dirty = True
                n_long += 1
            if active is not None and signal == "SELL" and clear_exit_only_if_flat(active, symbol, saved.shares):
                active_dirty = True
        assets[symbol] = {
            "cash": saved.cash,
            "shares": saved.shares,
            "peak": saved.peak,
            "trough": saved.trough,
            "last_price": price,
        }
        decisions.append(
            {
                "symbol": symbol,
                "price": price,
                "signal": signal,
                "signal_reason": signal_reason,
                "plan": plan_why,
                "action": exec_status,
                "shares": saved.shares,
                "peak": saved.peak,
                "trough": saved.trough,
                "rth_ok": rth_ok,
                "gate": gate_reason,
            }
        )
        _append_equity(
            paths.equity_path,
            {
                "Datetime": now_utc.isoformat(),
                "symbol": symbol,
                "Price": price,
                "Portfolio_Value": portfolio_value(saved, price),
            },
        )

    raw["assets"] = assets
    end_snapshot = broker.get_account_snapshot()
    end_report = reconcile(
        LocalSleeveState(
            cash=end_snapshot.cash_usd,
            shares={symbol: float(row.get("shares", 0.0)) for symbol, row in assets.items()},
        ),
        broker,
    )
    raw["cash_usd"] = end_report.corrected.cash
    for symbol, shares in end_report.corrected.shares.items():
        if symbol in assets:
            assets[symbol]["shares"] = shares
        if active is not None and clear_exit_only_if_flat(active, symbol, float(shares)):
            active_dirty = True

    if config.use_account_cash:
        # Book capital tracks full account equity; idle cash is split across flat sleeves.
        equity = float(getattr(end_snapshot, "equity_usd", 0.0) or 0.0)
        if equity > 0:
            config.total_cash = equity
            save_live_config(paths.config_path, config)
        avail = max(
            0.0,
            float(getattr(end_snapshot, "available_funds_usd", 0.0) or end_snapshot.spendable_usd or 0.0),
        )
        flat_syms = [
            sym
            for sym in config.symbols
            if float((assets.get(sym) or {}).get("shares") or 0.0) <= 0
            and not (active_flags.get(sym) and active_flags[sym].exit_only)
        ]
        if flat_syms and avail > 0:
            each = avail / float(len(flat_syms))
            for sym in flat_syms:
                row = assets.setdefault(
                    sym,
                    {"cash": 0.0, "shares": 0.0, "peak": None, "trough": None, "last_price": None},
                )
                row["cash"] = each

    raw["assets"] = assets
    _save_state(paths.state_path, raw)
    if active_dirty and active is not None:
        save_active(picker_paths.active_selection_path, active)
    return {
        "actions": actions,
        "mode": config.mode.value,
        "decisions": decisions,
        "rth_ok": rth_ok,
        "cash_usd": raw.get("cash_usd"),
        "trading_enabled": True,
        "use_account_cash": config.use_account_cash,
        "book_equity": config.total_cash if config.use_account_cash else None,
    }


def _safe_notify(kind: str, body: str, flags: dict | None) -> None:
    try:
        notify_live_event(kind, body, flags)
    except Exception as exc:  # noqa: BLE001
        print(f"notify_failed kind={kind} error={exc}")


def _latest_prices_yahoo(
    symbols: list[str],
) -> tuple[dict[str, float], dict[str, str], dict[str, list[float]]]:
    """Yahoo hourly closes (fallback when IBKR bars unavailable)."""
    import yfinance as yf

    prices: dict[str, float] = {}
    bars: dict[str, str] = {}
    closes: dict[str, list[float]] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1h")
        if hist is None or hist.empty:
            hist = ticker.history(period="5d", interval="1d")
        if hist is None or hist.empty:
            print(f"price_missing symbol={symbol}", file=sys.stderr)
            continue
        series = [float(x) for x in hist["Close"].tolist()]
        closes[symbol] = series
        last = hist.iloc[-1]
        prices[symbol] = float(last["Close"])
        idx = hist.index[-1]
        bars[symbol] = idx.isoformat() if hasattr(idx, "isoformat") else f"{symbol}:{now_iso}"
    return prices, bars, closes


def _unpack_hourly_book(
    result: object,
) -> tuple[dict[str, float], dict[str, str], dict[str, list[float]]]:
    """Accept 2-tuple (legacy) or 3-tuple (prices, bars, closes) from brokers."""
    if not isinstance(result, tuple):
        return {}, {}, {}
    if len(result) >= 3:
        prices, bars, closes = result[0], result[1], result[2]
        return dict(prices or {}), dict(bars or {}), dict(closes or {})
    if len(result) == 2:
        prices, bars = result
        return dict(prices or {}), dict(bars or {}), {}
    return {}, {}, {}


def _latest_prices(
    symbols: list[str], broker_inner=None
) -> tuple[dict[str, float], dict[str, str], dict[str, list[float]], str]:
    """IBKR RTH hourly TRADES primary; Yahoo is an explicit last-resort fallback.

    Also returns per-symbol close series for the first-buy SMA20 gate.
    """
    if not symbols:
        return {}, {}, {}, "no_symbols"
    if broker_inner is not None and hasattr(broker_inner, "latest_hourly_closes"):
        try:
            prices, bars, closes = _unpack_hourly_book(
                broker_inner.latest_hourly_closes(list(symbols), use_rth=True)
            )
            if prices:
                print(f"price_source=ibkr_rth_hourly n={len(prices)} closes={len(closes)}")
                return prices, bars, closes, "ibkr_rth_hourly"
            print("price_source=ibkr_empty; yahoo_fallback", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"price_source=ibkr_error ({exc}); yahoo_fallback", file=sys.stderr)
    prices, bars, closes = _latest_prices_yahoo(list(symbols))
    if prices:
        print(f"price_source=yahoo_fallback n={len(prices)} closes={len(closes)}")
    return prices, bars, closes, "yahoo_fallback"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one live-variant cycle")
    parser.add_argument("--mode", required=True, choices=[m.value for m in TradingMode if m != TradingMode.sim])
    parser.add_argument("--broker", default="memory", choices=["memory", "ibkr"])
    args = parser.parse_args(argv)
    mode = parse_mode(args.mode)
    if mode is TradingMode.live and os.environ.get("LIVE_TRADING_CONFIRM") != "YES":
        print("Refusing live mode without LIVE_TRADING_CONFIRM=YES", file=sys.stderr)
        raise SystemExit(1)
    if mode is TradingMode.live_dry_run:
        print("DRY RUN — NO ORDERS SENT")
    paths = LivePaths()
    bootstrap_live_state(paths.state_dir)
    config = load_live_config(paths.config_path)
    config.mode = mode
    from app.live.config import save_live_config

    save_live_config(paths.config_path, config)
    if args.broker == "ibkr":
        from app.broker.ibkr import IbkrBroker

        port = 4001 if mode is TradingMode.live else int(os.environ.get("IB_PORT", "4002"))
        try:
            inner = IbkrBroker(dry_run=mode is TradingMode.live_dry_run, port=port)
            clear_alert_cooldown("disconnect")
        except Exception as exc:  # noqa: BLE001
            print(f"ibkr_connect_failed: {exc}", file=sys.stderr)
            _safe_notify(
                "disconnect",
                "\n".join(
                    [
                        "IBKR Gateway connection failed",
                        "",
                        "What this means",
                        "  The live worker could not log in to IBKR this cycle.",
                        "  No orders will be placed until the connection recovers.",
                        "  Repeat disconnect emails are suppressed for ~6 hours.",
                        "",
                        "Details",
                        f"  Port:  {port}",
                        f"  Error: {exc}",
                        "",
                        "If AutoRestart failed",
                        "  1. Update paper login: ~/set_ib_paper_login.sh",
                        "  2. Restart gateway: sudo systemctl restart ibgateway.service",
                    ]
                ),
                config.alerts,
            )
            _write_last_cycle(
                paths,
                {
                    "ok": False,
                    "error": f"ibkr_connect_failed: {exc}",
                    "at_utc": datetime.now(timezone.utc).isoformat(),
                    "at_eastern": datetime.now(ZoneInfo("America/Toronto")).strftime(
                        "%Y-%m-%d %I:%M:%S %p %Z"
                    ),
                    "mode": config.mode.value,
                },
            )
            return 1
    else:
        inner = InMemoryBroker(cash_usd=config.total_cash)
    broker = BrokerGateway(inner, mode)
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    now = datetime.now(timezone.utc)
    prices, bars, closes, price_source = _latest_prices(list(config.symbols), broker_inner=inner)
    if not prices:
        print("No prices available; skipping cycle", file=sys.stderr)
        _write_last_cycle(
            paths,
            {
                "ok": False,
                "error": "no_prices",
                "at_utc": now.isoformat(),
                "at_eastern": datetime.now(ZoneInfo("America/Toronto")).strftime(
                    "%Y-%m-%d %I:%M:%S %p %Z"
                ),
                "mode": config.mode.value,
                "price_source": price_source,
            },
        )
        return 1
    try:
        summary = run_live_once(
            paths,
            broker,
            risk,
            audit,
            now,
            prices,
            bars,
            closes_by_symbol=closes,
        )
        print(summary)
        _write_last_cycle(
            paths,
            {
                "ok": True,
                "at_utc": now.isoformat(),
                "at_eastern": datetime.now(ZoneInfo("America/Toronto")).strftime(
                    "%Y-%m-%d %I:%M:%S %p %Z"
                ),
                "mode": summary.get("mode", config.mode.value),
                "price_source": price_source,
                "rth_ok": summary.get("rth_ok"),
                "cash_usd": summary.get("cash_usd"),
                "actions": summary.get("actions", []),
                "decisions": summary.get("decisions", []),
                "skipped": summary.get("skipped"),
            },
        )
    finally:
        ib = getattr(inner, "ib", None)
        if ib is not None and getattr(ib, "isConnected", lambda: False)():
            ib.disconnect()
    return 0


def _write_last_cycle(paths: LivePaths, payload: dict) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.last_cycle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
