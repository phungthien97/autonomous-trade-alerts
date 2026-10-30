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
from app.live.executor import execute_intent, flush_pending_queue
from app.notifier import clear_alert_cooldown, notify_live_event
from app.live.idempotency import IdempotencyStore
from app.live.modes import TradingMode, parse_mode
from app.live.planner import plan_from_signal
from app.live.queue import PendingIntent, PendingIntentStore
from app.live.reconcile import LocalSleeveState, reconcile
from app.live.session import is_us_equity_rth
from app.paths import LivePaths, PickerPaths, StatePaths
from app.picker.active import (
    clear_awaiting_first_buy,
    load_active,
    prune_exit_only_if_flat,
    reconcile_awaiting_first_buy,
    save_active,
)
from app.picker.apply import maybe_apply_pending
from app.picker.apply_live import remove_symbol_from_live_config
from app.live.account_nav import upsert_account_nav
from app.live.budget import (
    effective_buy_pool,
    equal_sleeve_target_usd,
    flat_buy_pool_usd,
    invested_usd,
    unused_budget,
)
from app.picker.sizing import resolve_equal_buy_cash_cap
from app.picker.trend_gate import allow_first_buy, sma
from app.risk.escalate import RiskController
from app.strategy import StrategyState, portfolio_value, step_signal

# Default max broker order submits per symbol per Eastern day
# (overridden by config.daily_order_cap).
DAILY_ORDER_CAP = 5


def _daily_order_cap(config) -> int:
    """Per-symbol daily submit cap (not account-wide)."""
    raw = getattr(config, "daily_order_cap", DAILY_ORDER_CAP)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DAILY_ORDER_CAP
    return value if value > 0 else DAILY_ORDER_CAP


def _orders_today_for_symbol(raw: dict, symbol: str) -> int:
    by_sym = raw.get("orders_today_by_symbol") or {}
    if not isinstance(by_sym, dict):
        return 0
    try:
        return int(by_sym.get(symbol) or 0)
    except (TypeError, ValueError):
        return 0


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


def _waiting_buy_reason(*, price: float, trough: float, buy_rise: float) -> str:
    trigger = float(trough) * (1.0 + float(buy_rise))
    pct = float(buy_rise) * 100.0
    return (
        f"Waiting: need {_fmt_usd(trigger)} "
        f"(+{pct:g}% from low {_fmt_usd(trough)}); now {_fmt_usd(price)}"
    )


def _waiting_sell_reason(*, price: float, peak: float, sell_drop: float) -> str:
    trigger = float(peak) * (1.0 - float(sell_drop))
    pct = float(sell_drop) * 100.0
    return (
        f"Holding: sell if at/under {_fmt_usd(trigger)} "
        f"(-{pct:g}% from high {_fmt_usd(peak)}); now {_fmt_usd(price)}"
    )


def _humanize_signal_reason(
    signal: str | None,
    *,
    price: float,
    trough_before: float | None,
    peak_before: float | None,
    fallback: str,
    shares: float = 0.0,
    buy_rise: float | None = None,
    sell_drop: float | None = None,
    trough_now: float | None = None,
    peak_now: float | None = None,
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
    if signal is None and fallback == "No signal":
        if shares <= 0 and trough_now is not None and buy_rise is not None:
            return _waiting_buy_reason(price=price, trough=trough_now, buy_rise=buy_rise)
        if shares > 0 and peak_now is not None and sell_drop is not None:
            return _waiting_sell_reason(price=price, peak=peak_now, sell_drop=sell_drop)
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
    # Reset daily order counters on Eastern calendar day change.
    orders_day = now_utc.astimezone(ZoneInfo("America/Toronto")).date().isoformat()
    if raw.get("orders_day") != orders_day:
        raw["orders_today"] = 0
        raw["orders_today_by_symbol"] = {}
        raw["orders_day"] = orders_day
    if not isinstance(raw.get("orders_today_by_symbol"), dict):
        raw["orders_today_by_symbol"] = {}
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

    # Stale awaiting_first_buy: already long at broker → treat as entered.
    broker_pos = broker.get_positions()
    share_map = {
        str(k).upper(): float(v)
        for k, v in {**report.corrected.shares, **broker_pos}.items()
    }
    if active is not None and reconcile_awaiting_first_buy(active, share_map):
        active_dirty = True
        active_flags = {row.symbol: row for row in active.symbols}

    # Flush parked outside-RTH intents once the session is open.
    if rth_ok:

        def _queue_gate(row: PendingIntent) -> str | None:
            flags = active_flags.get(row.symbol) or active_flags.get(str(row.symbol).upper())
            if row.side == "BUY" and flags is not None and flags.exit_only:
                return "exit_only"
            if row.side == "BUY" and flags is not None and flags.awaiting_first_buy:
                history = closes_by_symbol.get(row.symbol) or closes_by_symbol.get(
                    str(row.symbol).upper()
                ) or []
                px = float(price_by_symbol.get(row.symbol) or price_by_symbol.get(str(row.symbol).upper()) or 0.0)
                if px <= 0 or not allow_first_buy(history, price=px):
                    return "sma20_gate"
            return None

        flushed = flush_pending_queue(
            queue,
            broker=broker,
            idempotency=idem,
            audit=audit,
            mode=config.mode,
            allow_side=_queue_gate,
        )
        for row in flushed:
            actions.append(f"queue:{row.get('symbol')}:{row.get('status')}")
        if flushed:
            # Refresh after possible fills before the per-symbol loop.
            report = reconcile(
                LocalSleeveState(
                    cash=float(broker.get_account_snapshot().cash_usd),
                    shares={
                        symbol: float(broker.get_positions().get(symbol, 0.0))
                        for symbol in config.symbols
                    },
                ),
                broker,
            )
            raw["cash_usd"] = report.corrected.cash
            snapshot = broker.get_account_snapshot()

    # Seed trading budget once from spendable USD (wallet); never auto-track equity.
    if config.use_account_cash and config.trading_budget_usd is None:
        seed = max(0.0, float(snapshot.spendable_usd))
        if seed > 0:
            config.trading_budget_usd = seed
            save_live_config(paths.config_path, config)
            print(f"seeded trading_budget_usd={seed:.2f} from spendable_usd")

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
        # Fresh broker read each symbol — reconcile snapshot can lag mid-cycle fills.
        live_positions = broker.get_positions()
        broker_shares = float(live_positions.get(symbol, report.corrected.shares.get(symbol, 0.0)))
        exit_pending = bool(stored.get("exit_pending"))
        if broker_shares < -1e-9:
            assets[symbol] = {
                **stored,
                "shares": broker_shares,
                "last_price": price,
                "exit_pending": True,
            }
            decisions.append(
                {
                    "symbol": symbol,
                    "price": price,
                    "signal": None,
                    "signal_reason": f"SHORT BLOCKED: broker has {broker_shares:g} shares — cover manually",
                    "plan": "short_blocked",
                    "action": None,
                    "shares": broker_shares,
                    "peak": stored.get("peak"),
                    "trough": stored.get("trough"),
                    "rth_ok": rth_ok,
                    "gate": "never_short",
                }
            )
            actions.append(f"{symbol}:short_blocked")
            _safe_notify(
                "risk_alert",
                "\n".join(
                    [
                        f"Short detected on {symbol}",
                        "",
                        "Trading path blocked for this symbol.",
                        f"Broker shares: {broker_shares:g}",
                        "Cover to flat before re-enabling normal signals.",
                    ]
                ),
                config.alerts,
            )
            continue
        if exit_pending and broker_shares <= 1e-9:
            exit_pending = False
            stored["exit_pending"] = False
            stored["shares"] = 0.0
            stored["peak"] = None
        # While an exit is in flight, ignore strategy buys and only finish the sell.
        strategy_shares = max(0.0, broker_shares)
        before = StrategyState(
            cash=float(stored.get("cash", 0.0)),
            shares=0.0 if exit_pending and broker_shares <= 1e-9 else strategy_shares,
            peak=None if stored.get("peak") is None else float(stored["peak"]),
            trough=None if stored.get("trough") is None else float(stored["trough"]),
        )
        probe = StrategyState(cash=before.cash, shares=before.shares, peak=before.peak, trough=before.trough)
        trough_before = None if before.trough is None else float(before.trough)
        peak_before = None if before.peak is None else float(before.peak)
        if exit_pending and broker_shares > 1e-9:
            signal, signal_reason = "SELL", "Exit pending — selling remaining broker shares"
            probe = StrategyState(cash=before.cash, shares=broker_shares, peak=before.peak, trough=before.trough)
        else:
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
                shares=before.shares,
                buy_rise=asset.buy_rise_pct / 100.0,
                sell_drop=asset.sell_drop_pct / 100.0,
                trough_now=None if probe.trough is None else float(probe.trough),
                peak_now=None if probe.peak is None else float(probe.peak),
            )
        flags = active_flags.get(symbol)
        gate_reason = None
        if signal == "BUY" and exit_pending:
            signal = None
            gate_reason = "exit_pending"
            signal_reason = "Exit pending — buys blocked until flat"
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
        allow_frac = bool(
            config.allow_fractional_default and broker.supports_fractional(symbol)
        )
        if signal == "BUY":
            if config.use_account_cash:
                # Wallet pool for flats: unused minus USD reserved to top
                # underweight longs up to budget/N, then equal among flats
                # (+ 1-share stretch). Missing FX → 0.
                live_pos = broker.get_positions()
                marks = dict(price_by_symbol)
                price_book = getattr(broker, "inner", broker)
                if hasattr(price_book, "last_prices"):
                    for k, v in (price_book.last_prices or {}).items():
                        marks.setdefault(k, float(v))
                invested = invested_usd(live_pos, marks)
                active_syms = [
                    a.symbol
                    for a in config.assets
                    if a.enabled and not (active_flags.get(a.symbol) and active_flags[a.symbol].exit_only)
                ] or list(config.symbols)
                pool = flat_buy_pool_usd(
                    config.trading_budget_usd,
                    symbols=active_syms,
                    positions=live_pos,
                    prices=marks,
                    invested_usd=invested,
                    spendable_usd=float(snapshot.spendable_usd),
                )
                acct_ccy = str(getattr(snapshot, "account_currency", "") or "").upper()
                if pool <= 0 and acct_ccy not in {"USD", ""} and float(snapshot.spendable_usd) <= 0:
                    print(
                        f"{symbol}: BUY blocked — {acct_ccy} account has no IBKR FX "
                        f"path to USD (refusing {acct_ccy}-as-USD sizing)"
                    )
                elif pool <= 0 and config.trading_budget_usd is not None:
                    print(
                        f"{symbol}: BUY blocked — unused trading budget is 0 "
                        f"(budget={float(config.trading_budget_usd):.2f} invested={invested:.2f})"
                    )
                buy_cap = resolve_equal_buy_cash_cap(
                    pool,
                    n_active_non_exit_only=n_active,
                    n_already_long=n_long,
                    price=price,
                    allow_fractional=allow_frac,
                )
                # Never size a flat signal buy above equal sleeve target.
                if config.trading_budget_usd is not None and n_active > 0:
                    buy_cap = min(
                        float(buy_cap),
                        equal_sleeve_target_usd(float(config.trading_budget_usd), n_active),
                    )
            else:
                # Fixed paper book: sleeve cash, else budget-clamped spendable.
                sleeve_cash = max(0.0, float(before.cash))
                buy_cap = sleeve_cash if sleeve_cash > 0 else None
                if buy_cap is None:
                    live_pos = broker.get_positions()
                    invested = invested_usd(live_pos, price_by_symbol)
                    book = effective_buy_pool(
                        config.trading_budget_usd
                        if config.trading_budget_usd is not None
                        else float(config.total_cash),
                        invested_usd=invested,
                        spendable_usd=float(snapshot.spendable_usd),
                    )
                    buy_cap = resolve_equal_buy_cash_cap(
                        book,
                        n_active_non_exit_only=n_active,
                        n_already_long=n_long,
                        price=price,
                        allow_fractional=allow_frac,
                    )

        intent, plan_why = plan_from_signal(
            symbol,
            signal,
            before if not (exit_pending and broker_shares > 1e-9) else StrategyState(
                cash=before.cash,
                shares=broker_shares,
                peak=before.peak,
                trough=before.trough,
            ),
            price,
            allow_frac,
            snapshot,
            fee_schedule,
            bar_ts_by_symbol.get(symbol, now_utc.isoformat()),
            buy_cash_cap=buy_cap,
            broker_shares=broker_shares,
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
        orders_for_sym = _orders_today_for_symbol(raw, symbol)
        order_cap = _daily_order_cap(config)
        if intent is not None and orders_for_sym >= order_cap:
            # Per-symbol cap already hit — skip this ticker only; do not re-spam email.
            _, created = risk.trigger("max_orders", now_utc)
            exec_status = "skipped"
            plan_why = "daily order cap"
            actions.append(f"{symbol}:order_cap")
            if created:
                _safe_notify(
                    "risk_alert",
                    "\n".join(
                        [
                            f"Daily order cap hit — {symbol}",
                            "",
                            "What happened",
                            f"  {symbol} orders today: {orders_for_sym} (cap is {order_cap} per symbol).",
                            "  This symbol is blocked until you ack (counter also resets next Eastern day).",
                            "  Other symbols can still trade under their own caps.",
                            "  Raise the per-symbol cap in Live → Controls if you need more room today.",
                            "  Trading will auto-stop in 2 hours if you do not acknowledge.",
                        ]
                    ),
                    config.alerts,
                )
            intent = None
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
            if result.status in {"filled", "partial", "submitted"}:
                raw["orders_today"] = int(raw.get("orders_today", 0)) + 1
                by_sym = raw.setdefault("orders_today_by_symbol", {})
                if not isinstance(by_sym, dict):
                    by_sym = {}
                    raw["orders_today_by_symbol"] = by_sym
                by_sym[symbol] = int(by_sym.get(symbol) or 0) + 1
            if result.status == "rejected":
                raw["reject_streak"] = int(raw.get("reject_streak", 0)) + 1
            else:
                raw["reject_streak"] = 0
            if raw["reject_streak"] >= 3:
                _, created = risk.trigger("reject_storm", now_utc)
                if created:
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
            if _orders_today_for_symbol(raw, symbol) >= order_cap:
                _, created = risk.trigger("max_orders", now_utc)
                if created:
                    used_sym = _orders_today_for_symbol(raw, symbol)
                    _safe_notify(
                        "risk_alert",
                        "\n".join(
                            [
                                f"Daily order cap hit — {symbol}",
                                "",
                                "What happened",
                                f"  {symbol} orders today: {used_sym} (cap is {order_cap} per symbol).",
                                "  This symbol is blocked until you ack (counter also resets next Eastern day).",
                                "  Other symbols can still trade under their own caps.",
                                "  Raise the per-symbol cap in Live → Controls if you need more room today.",
                                "  Trading will auto-stop in 2 hours if you do not acknowledge.",
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
            # SELL submit must arm exit_pending even when IB returns submitted not filled,
            # otherwise the next hourly bar can sell the same long again and go short.
            if intent.side == "SELL" and result.status in {"submitted", "filled", "partial"}:
                exit_pending = True
            # Reserve this sleeve in the equal-split denominator as soon as a BUY
            # is live at the broker. Waiting for fill + awaiting_first_buy clear
            # left n_long stuck, so later same-cycle buys got spendable/n_flat
            # after cash already dropped → undersized sleeves.
            if intent.side == "BUY" and result.status in {"submitted", "filled", "partial"}:
                n_long += 1
        saved = probe if (signal is None or filled) else before
        if filled:
            saved.shares = float(broker.get_positions().get(symbol, saved.shares))
            saved.cash = 0.0 if saved.shares > 0 and signal == "BUY" else snapshot.cash_usd
            if active is not None and signal == "BUY" and clear_awaiting_first_buy(active, symbol):
                active_dirty = True
            if (
                active is not None
                and signal == "SELL"
                and prune_exit_only_if_flat(active, symbol, saved.shares)
            ):
                active_dirty = True
                updated = remove_symbol_from_live_config(paths.config_path, symbol)
                if updated is not None:
                    config = updated
                assets.pop(symbol, None)
                active_flags = {row.symbol: row for row in active.symbols}
        if exit_pending:
            # Optimistically flat locally so strategy cannot re-fire a full-size SELL.
            saved = StrategyState(
                cash=float(saved.cash),
                shares=0.0,
                peak=None,
                trough=price if saved.trough is None else saved.trough,
            )
        assets[symbol] = {
            "cash": saved.cash,
            "shares": max(0.0, float(saved.shares)),
            "peak": saved.peak,
            "trough": saved.trough,
            "last_price": price,
            "exit_pending": bool(exit_pending),
        }
        history = closes_by_symbol.get(symbol) or []
        sma20_val = sma(history) if history else None
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
                "sma20": round(float(sma20_val), 4) if sma20_val is not None else None,
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
        sh = float(shares)
        if symbol in assets:
            if sh < -1e-9:
                # Never persist a short as a normal long sleeve; keep blocked.
                assets[symbol]["shares"] = sh
                assets[symbol]["exit_pending"] = True
            elif bool(assets[symbol].get("exit_pending")) and sh > 1e-9:
                # Exit still working — keep local shares at 0 so we don't re-sell full size.
                assets[symbol]["shares"] = 0.0
            else:
                assets[symbol]["shares"] = max(0.0, sh)
                if sh <= 1e-9:
                    assets[symbol]["exit_pending"] = False
        if active is not None and prune_exit_only_if_flat(active, symbol, max(0.0, sh)):
            active_dirty = True
            updated = remove_symbol_from_live_config(paths.config_path, symbol)
            if updated is not None:
                config = updated
            assets.pop(symbol, None)
            active_flags = {row.symbol: row for row in active.symbols}

    # Raw AF kept for logging. Buy path uses trading_budget + spendable_usd.
    raw_af = getattr(end_snapshot, "available_funds_usd", None)
    spendable_native = max(
        0.0,
        float(getattr(end_snapshot, "spendable_native", None) or end_snapshot.spendable_usd),
    )
    spendable_usd = max(0.0, float(end_snapshot.spendable_usd))
    end_pos = broker.get_positions()
    end_marks = dict(price_by_symbol)
    for sym, row in assets.items():
        lp = row.get("last_price")
        if lp is not None and sym not in end_marks:
            try:
                end_marks[sym] = float(lp)
            except (TypeError, ValueError):
                pass
    end_invested = invested_usd(end_pos, end_marks)
    if config.use_account_cash:
        # NAV display only — do NOT set trading_budget from equity (deposits
        # must not auto-enlarge the wallet). Park unused budget (native) on
        # flat sleeves for dashboard labels; longs keep cash at 0.
        equity = float(getattr(end_snapshot, "equity_usd", 0.0) or 0.0)
        if equity > 0:
            config.total_cash = equity  # account NAV mirror, not buy ceiling
            save_live_config(paths.config_path, config)
        unused_usd = (
            unused_budget(float(config.trading_budget_usd), end_invested)
            if config.trading_budget_usd is not None
            else 0.0
        )
        # Convert unused USD → native for sleeve labels when CAD/BASE account.
        rate = getattr(end_snapshot, "usd_cad_rate", None)
        if rate is not None and float(rate) > 0:
            unused_native = unused_usd * float(rate)
        else:
            unused_native = unused_usd
        unused_native = min(unused_native, spendable_native)
        flat_syms: list[str] = []
        for sym in config.symbols:
            row = assets.setdefault(
                sym,
                {"cash": 0.0, "shares": 0.0, "peak": None, "trough": None, "last_price": None},
            )
            if float(row.get("shares") or 0.0) > 0:
                row["cash"] = 0.0
            elif not (active_flags.get(sym) and active_flags[sym].exit_only):
                flat_syms.append(sym)
        if flat_syms and unused_native > 0:
            each = unused_native / float(len(flat_syms))
            for sym in flat_syms:
                assets[sym]["cash"] = each
        elif flat_syms:
            for sym in flat_syms:
                assets[sym]["cash"] = 0.0

    raw["assets"] = assets
    raw["available_funds_usd"] = float(raw_af) if raw_af is not None else spendable_native
    raw["spendable_usd"] = spendable_usd
    raw["trading_budget_usd"] = (
        float(config.trading_budget_usd) if config.trading_budget_usd is not None else None
    )
    raw["invested_usd"] = end_invested
    raw["account_currency"] = str(getattr(end_snapshot, "account_currency", None) or "USD")
    rate = getattr(end_snapshot, "usd_cad_rate", None)
    raw["usd_cad_rate"] = float(rate) if rate is not None else None
    fx_map = getattr(end_snapshot, "fx_rates", None)
    if isinstance(fx_map, dict) and fx_map:
        raw["fx_rates"] = {str(k).upper(): float(v) for k, v in fx_map.items() if float(v) > 0}
    equity_for_nav = float(getattr(end_snapshot, "equity_usd", 0.0) or 0.0)
    if equity_for_nav <= 0 and config.use_account_cash:
        equity_for_nav = float(config.total_cash or 0.0)
    raw["broker_equity_usd"] = equity_for_nav if equity_for_nav > 0 else None
    gross = getattr(end_snapshot, "gross_position_value_usd", None)
    raw["gross_position_value_usd"] = float(gross) if gross is not None else None
    accrued = getattr(end_snapshot, "accrued_cash_usd", None)
    raw["accrued_cash_usd"] = float(accrued) if accrued is not None else None
    _save_state(paths.state_path, raw)
    if equity_for_nav > 0:
        upsert_account_nav(paths.account_nav_path, equity=equity_for_nav, at=now_utc)
    if active_dirty and active is not None:
        save_active(picker_paths.active_selection_path, active)
    return {
        "actions": actions,
        "mode": config.mode.value,
        "decisions": decisions,
        "rth_ok": rth_ok,
        "cash_usd": raw.get("cash_usd"),
        "available_funds_usd": raw.get("available_funds_usd"),
        "spendable_usd": raw.get("spendable_usd"),
        "trading_budget_usd": raw.get("trading_budget_usd"),
        "invested_usd": raw.get("invested_usd"),
        "account_currency": raw.get("account_currency"),
        "usd_cad_rate": raw.get("usd_cad_rate"),
        "fx_rates": raw.get("fx_rates"),
        "trading_enabled": True,
        "use_account_cash": config.use_account_cash,
        "book_equity": config.total_cash if config.use_account_cash else None,
        "gross_position_value_usd": raw.get("gross_position_value_usd"),
        "accrued_cash_usd": raw.get("accrued_cash_usd"),
        "orders_today": int(raw.get("orders_today") or 0),
        "orders_today_by_symbol": {
            str(k): int(v)
            for k, v in (raw.get("orders_today_by_symbol") or {}).items()
            if v is not None
        },
        "daily_order_cap": _daily_order_cap(config),
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
                "available_funds_usd": summary.get("available_funds_usd"),
                "spendable_usd": summary.get("spendable_usd"),
                "trading_budget_usd": summary.get("trading_budget_usd"),
                "invested_usd": summary.get("invested_usd"),
                "account_currency": summary.get("account_currency"),
                "usd_cad_rate": summary.get("usd_cad_rate"),
                "fx_rates": summary.get("fx_rates"),
                "actions": summary.get("actions", []),
                "decisions": summary.get("decisions", []),
                "skipped": summary.get("skipped"),
                "use_account_cash": summary.get("use_account_cash"),
                "book_equity": summary.get("book_equity"),
                "gross_position_value_usd": summary.get("gross_position_value_usd"),
                "accrued_cash_usd": summary.get("accrued_cash_usd"),
                "orders_today": summary.get("orders_today"),
                "orders_today_by_symbol": summary.get("orders_today_by_symbol"),
                "daily_order_cap": summary.get("daily_order_cap"),
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
