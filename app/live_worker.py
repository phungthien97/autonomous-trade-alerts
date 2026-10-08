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

from app.audit.log import AuditLog
from app.broker.memory import InMemoryBroker
from app.fees import default_ibkr_us_stock_schedule
from app.broker.gateway import BrokerGateway
from app.live.config import bootstrap_live_state, load_live_config
from app.live.executor import execute_intent
from app.notifier import notify_live_event
from app.live.idempotency import IdempotencyStore
from app.live.modes import TradingMode, parse_mode
from app.live.planner import plan_from_signal
from app.live.queue import PendingIntentStore
from app.live.reconcile import LocalSleeveState, reconcile
from app.live.session import is_us_equity_rth
from app.paths import LivePaths
from app.risk.escalate import RiskController
from app.strategy import StrategyState, portfolio_value, step_signal


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
) -> dict:
    bootstrap_live_state(paths.state_dir)
    config = load_live_config(paths.config_path)
    broker = broker if isinstance(broker, BrokerGateway) else BrokerGateway(broker, config.mode)
    stopped_now = risk.tick(now_utc)
    if stopped_now:
        _safe_notify("trading_stopped", "No ack within 2 hours. Trading disabled.", config.alerts)
    if not risk.trading_enabled or not config.trading_enabled:
        return {"skipped": "trading_disabled"}

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
    rth_ok = is_us_equity_rth(now_utc)
    actions: list[str] = []
    idem = IdempotencyStore(paths.idempotency_path)
    queue = PendingIntentStore(paths.queue_path)

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
        signal, _reason = step_signal(
            probe,
            price,
            asset.buy_rise_pct / 100.0,
            asset.sell_drop_pct / 100.0,
        )
        intent, _why = plan_from_signal(
            symbol,
            signal,
            before,
            price,
            config.allow_fractional_default and broker.supports_fractional(symbol),
            snapshot,
            fee_schedule,
            bar_ts_by_symbol.get(symbol, now_utc.isoformat()),
        )
        filled = False
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
            actions.append(f"{symbol}:{result.status}")
            raw["orders_today"] = int(raw.get("orders_today", 0)) + (1 if result.status in {"filled", "partial", "submitted"} else 0)
            if result.status == "rejected":
                raw["reject_streak"] = int(raw.get("reject_streak", 0)) + 1
            else:
                raw["reject_streak"] = 0
            if raw["reject_streak"] >= 3:
                risk.trigger("reject_storm", now_utc)
                _safe_notify("risk_alert", "Repeated order rejects.", config.alerts)
            if raw["orders_today"] > 6:
                risk.trigger("max_orders", now_utc)
                _safe_notify("risk_alert", "Max orders for the day exceeded.", config.alerts)
            if result.status == "filled":
                _safe_notify("fill", f"{symbol} filled {intent.quantity}", config.alerts)
            elif result.status == "rejected":
                _safe_notify("reject", f"{symbol} rejected", config.alerts)
            filled = result.status == "filled"
            snapshot = broker.get_account_snapshot()
        saved = probe if (signal is None or filled) else before
        if filled:
            saved.shares = float(broker.get_positions().get(symbol, saved.shares))
            saved.cash = 0.0 if saved.shares > 0 and signal == "BUY" else snapshot.cash_usd
        assets[symbol] = {
            "cash": saved.cash,
            "shares": saved.shares,
            "peak": saved.peak,
            "trough": saved.trough,
            "last_price": price,
        }
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
    end_report = reconcile(
        LocalSleeveState(
            cash=broker.get_account_snapshot().cash_usd,
            shares={symbol: float(row.get("shares", 0.0)) for symbol, row in assets.items()},
        ),
        broker,
    )
    raw["cash_usd"] = end_report.corrected.cash
    for symbol, shares in end_report.corrected.shares.items():
        if symbol in assets:
            assets[symbol]["shares"] = shares
    raw["assets"] = assets
    _save_state(paths.state_path, raw)
    return {"actions": actions, "mode": config.mode.value}


def _safe_notify(kind: str, body: str, flags: dict | None) -> None:
    try:
        notify_live_event(kind, body, flags)
    except Exception as exc:  # noqa: BLE001
        print(f"notify_failed kind={kind} error={exc}")


def _latest_prices_yahoo(symbols: list[str]) -> tuple[dict[str, float], dict[str, str]]:
    """Yahoo hourly closes (fallback when IBKR bars unavailable)."""
    import yfinance as yf

    prices: dict[str, float] = {}
    bars: dict[str, str] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1h")
        if hist is None or hist.empty:
            hist = ticker.history(period="5d", interval="1d")
        if hist is None or hist.empty:
            print(f"price_missing symbol={symbol}", file=sys.stderr)
            continue
        last = hist.iloc[-1]
        prices[symbol] = float(last["Close"])
        idx = hist.index[-1]
        bars[symbol] = idx.isoformat() if hasattr(idx, "isoformat") else f"{symbol}:{now_iso}"
    return prices, bars


def _latest_prices(symbols: list[str], broker_inner=None) -> tuple[dict[str, float], dict[str, str]]:
    """Prefer IBKR RTH hourly TRADES bars when connected; else Yahoo (R6)."""
    if broker_inner is not None and hasattr(broker_inner, "latest_hourly_closes"):
        try:
            prices, bars = broker_inner.latest_hourly_closes(list(symbols), use_rth=True)
            if prices:
                print(f"price_source=ibkr_rth_hourly n={len(prices)}")
                return prices, bars
            print("price_source=ibkr_empty; falling_back_yahoo", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"price_source=ibkr_error ({exc}); falling_back_yahoo", file=sys.stderr)
    prices, bars = _latest_prices_yahoo(list(symbols))
    if prices:
        print(f"price_source=yahoo_hourly n={len(prices)}")
    return prices, bars


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
        except Exception as exc:  # noqa: BLE001
            print(f"ibkr_connect_failed: {exc}", file=sys.stderr)
            _safe_notify(
                "disconnect",
                f"IBKR connect failed on port {port}: {exc}",
                config.alerts,
            )
            return 1
    else:
        inner = InMemoryBroker(cash_usd=config.total_cash)
    broker = BrokerGateway(inner, mode)
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    now = datetime.now(timezone.utc)
    prices, bars = _latest_prices(list(config.symbols), broker_inner=inner)
    if not prices:
        print("No prices available; skipping cycle", file=sys.stderr)
        return 1
    try:
        summary = run_live_once(paths, broker, risk, audit, now, prices, bars)
        print(summary)
    finally:
        ib = getattr(inner, "ib", None)
        if ib is not None and getattr(ib, "isConnected", lambda: False)():
            ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
