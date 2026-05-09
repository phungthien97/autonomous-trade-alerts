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


def _normalize_assets(config: dict) -> list[dict]:
    assets = config.get("assets")
    if isinstance(assets, list) and assets:
        normalized = []
        for asset in assets:
            symbol = str(asset.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            normalized.append(
                {
                    "symbol": symbol,
                    "buy_rise_pct": float(asset.get("buy_rise_pct", config.get("buy_rise_pct", 1.0))),
                    "sell_drop_pct": float(asset.get("sell_drop_pct", config.get("sell_drop_pct", 1.5))),
                    "x_days": int(asset.get("x_days", config.get("x_days", 20))),
                    "reopt_days": int(asset.get("reopt_days", config.get("reopt_days", 5))),
                    "enabled": bool(asset.get("enabled", True)),
                }
            )
        if normalized:
            return normalized
    return []


def _reoptimize_if_due(asset_cfg: dict, asset_state: dict, initial_cash: float, now_utc: datetime) -> tuple[float, float, bool]:
    reopt_days = int(asset_cfg["reopt_days"])
    x_days = int(asset_cfg["x_days"])
    symbol = asset_cfg["symbol"]
    last_reopt = asset_state.get("last_reopt_at")
    due = True
    if last_reopt:
        due = (now_utc - datetime.fromisoformat(last_reopt.replace("Z", "+00:00"))) >= timedelta(days=reopt_days)

    buy_rise = float(asset_cfg["buy_rise_pct"]) / 100.0
    sell_drop = float(asset_cfg["sell_drop_pct"]) / 100.0
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
        initial_cash=initial_cash,
    )
    asset_cfg["buy_rise_pct"] = round(best_buy * 100.0, 3)
    asset_cfg["sell_drop_pct"] = round(best_sell * 100.0, 3)
    asset_state["last_reopt_at"] = now_utc.isoformat().replace("+00:00", "Z")
    _append_csv(
        PARAMS_PATH,
        {
            "Datetime": asset_state["last_reopt_at"],
            "symbol": symbol,
            "x_days": x_days,
            "buy_rise_pct": asset_cfg["buy_rise_pct"],
            "sell_drop_pct": asset_cfg["sell_drop_pct"],
            "train_final_value": train_final,
        },
    )
    return best_buy, best_sell, True


def run_once() -> None:
    now_utc = datetime.now(timezone.utc)
    config = _read_json(CONFIG_PATH)
    state = _read_json(STATE_PATH)
    assets = _normalize_assets(config)
    enabled_assets = [a for a in assets if a.get("enabled", True)]
    if not enabled_assets:
        raise RuntimeError("No enabled assets configured.")

    if "assets" not in state or not isinstance(state.get("assets"), dict):
        state["assets"] = {}

    # initial_cash is interpreted as per-asset starting capital.
    per_asset_initial = float(config["initial_cash"])
    end = (now_utc.date() + timedelta(days=1)).isoformat()
    start = max(datetime.strptime(hourly_limit_start_date(), "%Y-%m-%d").date(), now_utc.date() - timedelta(days=7))

    total_value = 0.0
    last_actions: list[str] = []
    processed_assets = 0
    changed_any = False

    for asset_cfg in enabled_assets:
        symbol = asset_cfg["symbol"]
        asset_state = state["assets"].get(
            symbol,
            {
                "cash": per_asset_initial,
                "shares": 0.0,
                "peak": None,
                "trough": None,
                "last_price": 0.0,
                "last_action": "HOLD",
                "last_signal_reason": "No signal",
                "last_bar_at": None,
                "last_reopt_at": None,
                "initial_cash": per_asset_initial,
            },
        )
        state["assets"][symbol] = asset_state

        try:
            recent_df = download_hourly(symbol=symbol, start=str(start), end=end)
        except Exception as exc:  # noqa: BLE001
            # Skip invalid/delisted symbols instead of failing entire workflow.
            asset_state["last_action"] = "SKIP"
            asset_state["last_signal_reason"] = f"Data unavailable: {exc}"
            last_actions.append(f"{symbol}:ERROR")
            print(f"skip_symbol={symbol} reason={exc}")
            continue
        latest = recent_df.iloc[-1]
        latest_dt = pd.Timestamp(latest["Datetime"])
        latest_price = float(latest["Close"])
        prev_bar_raw = asset_state.get("last_bar_at")
        prev_bar = pd.to_datetime(prev_bar_raw, utc=True, errors="coerce") if prev_bar_raw else pd.NaT
        if pd.notna(prev_bar) and latest_dt <= prev_bar:
            # No new bar for this symbol since last run: skip writes to reduce churn.
            existing_val = float(asset_state.get("cash", 0.0)) + float(asset_state.get("shares", 0.0)) * float(asset_state.get("last_price", 0.0))
            total_value += existing_val
            last_actions.append(f"{symbol}:SKIP")
            continue
        processed_assets += 1

        strategy_state = StrategyState(
            cash=float(asset_state["cash"]),
            shares=float(asset_state["shares"]),
            peak=None if asset_state.get("peak") is None else float(asset_state["peak"]),
            trough=None if asset_state.get("trough") is None else float(asset_state["trough"]),
        )

        symbol_initial_cash = float(asset_state.get("initial_cash", per_asset_initial))
        if strategy_state.cash == symbol_initial_cash and strategy_state.shares == 0.0:
            strategy_state.shares = symbol_initial_cash / latest_price
            strategy_state.cash = 0.0
            strategy_state.peak = latest_price
            strategy_state.trough = None
            _append_csv(
                TRADES_PATH,
                {
                    "Datetime": latest_dt.isoformat(),
                    "symbol": symbol,
                    "Action": "BUY",
                    "Price": latest_price,
                    "Shares_After": strategy_state.shares,
                    "Cash_After": strategy_state.cash,
                    "Portfolio_Value": portfolio_value(strategy_state, latest_price),
                    "buy_rise_pct": asset_cfg["buy_rise_pct"],
                    "sell_drop_pct": asset_cfg["sell_drop_pct"],
                    "Reason": "Initial full allocation",
                },
            )
            changed_any = True

        buy_rise, sell_drop, reoptimized = _reoptimize_if_due(
            asset_cfg=asset_cfg,
            asset_state=asset_state,
            initial_cash=symbol_initial_cash,
            now_utc=now_utc,
        )
        action, reason = step_signal(strategy_state, latest_price, buy_rise=buy_rise, sell_drop=sell_drop)
        port_val = portfolio_value(strategy_state, latest_price)
        total_value += port_val

        if action:
            _append_csv(
                TRADES_PATH,
                {
                    "Datetime": latest_dt.isoformat(),
                    "symbol": symbol,
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
            changed_any = True
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
        changed_any = True

        asset_state["cash"] = strategy_state.cash
        asset_state["shares"] = strategy_state.shares
        asset_state["peak"] = strategy_state.peak
        asset_state["trough"] = strategy_state.trough
        asset_state["last_price"] = latest_price
        asset_state["last_action"] = action or "HOLD"
        asset_state["last_signal_reason"] = reason
        asset_state["last_bar_at"] = latest_dt.isoformat()
        asset_state["initial_cash"] = symbol_initial_cash
        last_actions.append(f"{symbol}:{asset_state['last_action']}")
        changed_any = True

    if processed_assets == 0 and not changed_any:
        print("no_new_bars=true")
        print(f"assets={','.join([a['symbol'] for a in enabled_assets])}")
        return

    # Keep legacy top-level keys in sync for dashboard/backward compatibility.
    primary_symbol = enabled_assets[0]["symbol"]
    primary_state = state["assets"][primary_symbol]
    state["cash"] = primary_state["cash"]
    state["shares"] = primary_state["shares"]
    state["peak"] = primary_state["peak"]
    state["trough"] = primary_state["trough"]
    state["last_price"] = primary_state["last_price"]
    state["last_action"] = primary_state["last_action"]
    state["last_signal_reason"] = primary_state["last_signal_reason"]
    state["last_bar_at"] = primary_state["last_bar_at"]
    state["last_reopt_at"] = primary_state.get("last_reopt_at")
    state["portfolio_value"] = total_value
    state["last_run_at"] = now_utc.isoformat().replace("+00:00", "Z")

    config["assets"] = assets
    _write_json(STATE_PATH, state)
    _write_json(CONFIG_PATH, config)

    print(f"assets={','.join([a['symbol'] for a in enabled_assets])}")
    print(f"last_actions={';'.join(last_actions)}")
    print(f"portfolio_value={total_value:.6f}")


if __name__ == "__main__":
    run_once()
