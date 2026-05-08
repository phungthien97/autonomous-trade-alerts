from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.data import download_hourly, hourly_limit_start_date
from app.notifier import send_signal_email
from app.strategy import StrategyState, optimize_params, portfolio_value, step_signal


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
CONFIG_PATH = STATE_DIR / "config.json"
STATE_PATH = STATE_DIR / "state.json"
TRADES_PATH = STATE_DIR / "trades.csv"
EQUITY_PATH = STATE_DIR / "equity.csv"
PARAMS_PATH = STATE_DIR / "params_history.csv"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append_csv(path: Path, row: dict) -> None:
    row_df = pd.DataFrame([row])
    if path.exists():
        prev = pd.read_csv(path)
        out = pd.concat([prev, row_df], ignore_index=True)
    else:
        out = row_df
    out.to_csv(path, index=False)


def _reoptimize_if_due(config: dict, state: dict, now_utc: datetime) -> tuple[float, float, bool]:
    reopt_days = int(config["reopt_days"])
    x_days = int(config["x_days"])
    symbol = config["symbol"]

    last_reopt = state.get("last_reopt_at")
    due = True
    if last_reopt:
        due = (now_utc - datetime.fromisoformat(last_reopt.replace("Z", "+00:00"))) >= timedelta(days=reopt_days)

    buy_rise = float(config["buy_rise_pct"]) / 100.0
    sell_drop = float(config["sell_drop_pct"]) / 100.0
    if not due:
        return buy_rise, sell_drop, False

    end = (now_utc.date() + timedelta(days=1)).isoformat()
    start_date = max(
        datetime.strptime(hourly_limit_start_date(), "%Y-%m-%d").date(),
        now_utc.date() - timedelta(days=max(x_days + 7, 45)),
    )
    train_df = download_hourly(symbol=symbol, start=str(start_date), end=end)
    unique_days = sorted(train_df["TradeDate"].unique())
    if len(unique_days) < 2:
        return buy_rise, sell_drop, False
    train_days = unique_days[-x_days:] if len(unique_days) > x_days else unique_days
    train_prices = train_df[train_df["TradeDate"].isin(train_days)]["Close"].astype(float).to_numpy()
    if len(train_prices) < 2:
        return buy_rise, sell_drop, False

    best_buy, best_sell, train_final = optimize_params(
        train_prices=train_prices,
        initial_cash=float(config["initial_cash"]),
    )
    config["buy_rise_pct"] = round(best_buy * 100.0, 3)
    config["sell_drop_pct"] = round(best_sell * 100.0, 3)
    state["last_reopt_at"] = now_utc.isoformat().replace("+00:00", "Z")
    _append_csv(
        PARAMS_PATH,
        {
            "Datetime": state["last_reopt_at"],
            "symbol": symbol,
            "x_days": x_days,
            "buy_rise_pct": config["buy_rise_pct"],
            "sell_drop_pct": config["sell_drop_pct"],
            "train_final_value": train_final,
        },
    )
    return best_buy, best_sell, True


def run_once() -> None:
    now_utc = datetime.now(timezone.utc)
    config = _read_json(CONFIG_PATH)
    state = _read_json(STATE_PATH)

    symbol = config["symbol"]
    initial_cash = float(config["initial_cash"])

    end = (now_utc.date() + timedelta(days=1)).isoformat()
    start = max(datetime.strptime(hourly_limit_start_date(), "%Y-%m-%d").date(), now_utc.date() - timedelta(days=7))
    recent_df = download_hourly(symbol=symbol, start=str(start), end=end)
    latest = recent_df.iloc[-1]
    latest_dt = pd.Timestamp(latest["Datetime"])
    latest_price = float(latest["Close"])

    strategy_state = StrategyState(
        cash=float(state["cash"]),
        shares=float(state["shares"]),
        peak=None if state["peak"] is None else float(state["peak"]),
        trough=None if state["trough"] is None else float(state["trough"]),
    )

    if strategy_state.cash == initial_cash and strategy_state.shares == 0.0:
        strategy_state.shares = initial_cash / latest_price
        strategy_state.cash = 0.0
        strategy_state.peak = latest_price
        strategy_state.trough = None
        _append_csv(
            TRADES_PATH,
            {
                "Datetime": latest_dt.isoformat(),
                "Action": "BUY",
                "Price": latest_price,
                "Shares_After": strategy_state.shares,
                "Cash_After": strategy_state.cash,
                "Portfolio_Value": portfolio_value(strategy_state, latest_price),
                "buy_rise_pct": config["buy_rise_pct"],
                "sell_drop_pct": config["sell_drop_pct"],
                "Reason": "Initial full allocation",
            },
        )

    buy_rise, sell_drop, reoptimized = _reoptimize_if_due(config=config, state=state, now_utc=now_utc)
    action, reason = step_signal(strategy_state, latest_price, buy_rise=buy_rise, sell_drop=sell_drop)
    port_val = portfolio_value(strategy_state, latest_price)

    if action:
        _append_csv(
            TRADES_PATH,
            {
                "Datetime": latest_dt.isoformat(),
                "Action": action,
                "Price": latest_price,
                "Shares_After": strategy_state.shares,
                "Cash_After": strategy_state.cash,
                "Portfolio_Value": port_val,
                "buy_rise_pct": buy_rise * 100.0,
                "sell_drop_pct": sell_drop * 100.0,
                "Reason": reason,
            },
        )
        if bool(config.get("alerts_enabled", True)):
            send_signal_email(
                subject=f"[ALERT] {action} {symbol} @ {latest_price:.2f}",
                body=(
                    f"Signal: {action}\n"
                    f"Symbol: {symbol}\n"
                    f"Time: {latest_dt.isoformat()}\n"
                    f"Price: {latest_price:.4f}\n"
                    f"Shares after: {strategy_state.shares:.8f}\n"
                    f"Cash after: {strategy_state.cash:.2f}\n"
                    f"Portfolio value: {port_val:.2f}\n"
                    f"Thresholds: buy_rise={buy_rise*100:.3f}% sell_drop={sell_drop*100:.3f}%\n"
                    f"Reoptimized this run: {reoptimized}"
                ),
            )

    _append_csv(
        EQUITY_PATH,
        {
            "Datetime": latest_dt.isoformat(),
            "symbol": symbol,
            "Close": latest_price,
            "Shares": strategy_state.shares,
            "Cash": strategy_state.cash,
            "Portfolio_Value": port_val,
            "buy_rise_pct": buy_rise * 100.0,
            "sell_drop_pct": sell_drop * 100.0,
        },
    )

    state["cash"] = strategy_state.cash
    state["shares"] = strategy_state.shares
    state["peak"] = strategy_state.peak
    state["trough"] = strategy_state.trough
    state["last_price"] = latest_price
    state["last_action"] = action or "HOLD"
    state["last_signal_reason"] = reason
    state["last_run_at"] = now_utc.isoformat().replace("+00:00", "Z")
    state["last_bar_at"] = latest_dt.isoformat()
    _write_json(STATE_PATH, state)
    _write_json(CONFIG_PATH, config)

    print(f"symbol={symbol}")
    print(f"latest_price={latest_price:.6f}")
    print(f"action={state['last_action']}")
    print(f"portfolio_value={port_val:.6f}")
    print(f"reoptimized={reoptimized}")


if __name__ == "__main__":
    run_once()
