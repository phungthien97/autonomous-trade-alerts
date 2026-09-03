from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.strategy import optimize_params_v2, portfolio_value, run_fixed_params, step_signal
from app.strategy import StrategyState


META_HISTORY_COLUMNS = [
    "Datetime",
    "lambda_per_trip",
    "base_floor_pct",
    "max_buy_pct",
    "train_days",
    "validate_days",
    "simulation_score",
]


def _price_volatility(prices: np.ndarray) -> float:
    if len(prices) < 2:
        return 0.0
    returns = np.diff(prices.astype(float)) / prices[:-1]
    return float(np.std(returns))


def _append_csv(path: Path, row: dict, columns: list[str] | None = None) -> None:
    row_df = pd.DataFrame([row])
    if path.exists() and path.stat().st_size > 0:
        prev = pd.read_csv(path)
        out = pd.concat([prev, row_df], ignore_index=True)
    else:
        out = row_df if columns is None else row_df.reindex(columns=columns)
    out.to_csv(path, index=False)


def _split_train_validate(prices_by_day: list[np.ndarray], train_days: int, validate_days: int) -> tuple[np.ndarray, np.ndarray] | None:
    if len(prices_by_day) < 2:
        return None
    train_block = prices_by_day[-(train_days + validate_days) : -validate_days] if len(prices_by_day) > train_days + validate_days else prices_by_day[:-1]
    validate_block = prices_by_day[-validate_days:] if validate_days > 0 else prices_by_day[-1:]
    if not train_block or not validate_block:
        return None
    train_prices = np.concatenate(train_block)
    validate_prices = np.concatenate(validate_block)
    if len(train_prices) < 2 or len(validate_prices) < 2:
        return None
    return train_prices, validate_prices


def _simulate_symbol(
    df: pd.DataFrame,
    meta: dict,
    initial_cash: float,
    reopt_days: int,
    simulation_weeks: int,
) -> tuple[float, float]:
    if df.empty:
        return initial_cash, 0.0
    unique_days = sorted(df["TradeDate"].unique())
    lookback_days = max(int(simulation_weeks * 7), reopt_days + meta.get("train_days", 15) + meta.get("validate_days", 5) + 2)
    sim_days = unique_days[-lookback_days:] if len(unique_days) > lookback_days else unique_days
    if len(sim_days) < 3:
        return initial_cash, 0.0

    prices_by_day = [
        df[df["TradeDate"] == day]["Close"].astype(float).to_numpy()
        for day in sim_days
        if len(df[df["TradeDate"] == day]) > 0
    ]
    if len(prices_by_day) < 2:
        return initial_cash, 0.0

    all_train_prices = np.concatenate(prices_by_day)
    median_vol = _price_volatility(all_train_prices)
    symbol_vol = median_vol

    first_price = float(prices_by_day[0][0])
    state = StrategyState(cash=0.0, shares=initial_cash / first_price, peak=first_price, trough=None)
    buy_rise = float(meta.get("base_floor_pct", 2.0)) / 100.0
    sell_drop = buy_rise
    peak_value = initial_cash
    max_drawdown = 0.0
    round_trips = 0

    i = int(meta.get("train_days", 15)) + int(meta.get("validate_days", 5))
    while i < len(prices_by_day):
        history = prices_by_day[:i]
        split = _split_train_validate(
            history,
            train_days=int(meta.get("train_days", 15)),
            validate_days=int(meta.get("validate_days", 5)),
        )
        if split:
            train_prices, validate_prices = split
            symbol_vol = _price_volatility(train_prices)
            current = (buy_rise, sell_drop)
            buy_rise, sell_drop, _, accepted, _ = optimize_params_v2(
                train_prices=train_prices,
                validate_prices=validate_prices,
                current=current,
                meta=meta,
                initial_cash=initial_cash,
                symbol_vol=symbol_vol,
                median_vol=median_vol or symbol_vol or 0.01,
            )
            if not accepted:
                pass

        block = prices_by_day[i : i + reopt_days]
        for day_prices in block:
            for price in day_prices:
                action, _ = step_signal(state, float(price), buy_rise=buy_rise, sell_drop=sell_drop)
                if action == "SELL":
                    round_trips += 1
                val = portfolio_value(state, float(price))
                peak_value = max(peak_value, val)
                if peak_value > 0:
                    max_drawdown = max(max_drawdown, (peak_value - val) / peak_value)
        i += reopt_days

    final_price = float(prices_by_day[-1][-1])
    final_value = portfolio_value(state, final_price)
    return final_value, max_drawdown + round_trips


def score_meta_config(
    hourly_by_symbol: dict[str, pd.DataFrame],
    assets: list[dict],
    meta: dict,
    initial_cash: float,
) -> float:
    enabled = [a for a in assets if a.get("enabled", True)]
    if not enabled:
        return float("-inf")

    total_final = 0.0
    total_trips_penalty = 0.0
    max_dd = 0.0
    for asset in enabled:
        symbol = asset["symbol"]
        df = hourly_by_symbol.get(symbol)
        if df is None or df.empty:
            continue
        final_value, penalty_proxy = _simulate_symbol(
            df=df,
            meta=meta,
            initial_cash=initial_cash,
            reopt_days=int(asset.get("reopt_days", 5)),
            simulation_weeks=int(meta.get("simulation_weeks", 8)),
        )
        total_final += final_value
        total_trips_penalty += penalty_proxy
        max_dd = max(max_dd, penalty_proxy)

    if total_final <= 0:
        return float("-inf")
    return_pct = (total_final / (initial_cash * len(enabled)) - 1.0) * 100.0
    lambda_per_trip = float(meta.get("lambda_per_trip", 10.0))
    drawdown_penalty = max_dd * 100.0
    return return_pct - lambda_per_trip * 0.1 - drawdown_penalty


def _meta_is_due(meta: dict, now_utc: datetime) -> bool:
    meta_reopt_days = int(meta.get("meta_reopt_days", 28))
    last_meta_at = meta.get("last_meta_at")
    if not last_meta_at:
        return True
    return (now_utc - datetime.fromisoformat(str(last_meta_at).replace("Z", "+00:00"))) >= timedelta(days=meta_reopt_days)


def run_meta_if_due(
    config: dict,
    meta_history_path: Path,
    now_utc: datetime,
    hourly_by_symbol: dict[str, pd.DataFrame],
) -> bool:
    meta = dict(config.get("meta") or {})
    meta_reopt_days = int(meta.get("meta_reopt_days", 28))
    last_meta_at = meta.get("last_meta_at")
    due = True
    if last_meta_at:
        due = (now_utc - datetime.fromisoformat(str(last_meta_at).replace("Z", "+00:00"))) >= timedelta(days=meta_reopt_days)
    if not due:
        return False

    assets = config.get("assets") or []
    initial_cash = float(config.get("initial_cash", 1000.0))
    base_meta = {
        "lambda_per_trip": float(meta.get("lambda_per_trip", 10.0)),
        "base_floor_pct": float(meta.get("base_floor_pct", 2.0)),
        "max_buy_pct": float(meta.get("max_buy_pct", 8.0)),
        "train_days": int(meta.get("train_days", 15)),
        "validate_days": int(meta.get("validate_days", 5)),
        "simulation_weeks": int(meta.get("simulation_weeks", 8)),
        "meta_reopt_days": meta_reopt_days,
        "min_floor_pct": float(meta.get("min_floor_pct", 1.0)),
        "max_floor_pct": float(meta.get("max_floor_pct", 5.0)),
    }

    grid = itertools.product(
        [10.0, 20.0],
        [2.0, 2.5],
        [8.0, 10.0],
        [15, 18],
        [5, 6],
    )
    best_score = float("-inf")
    best_meta = base_meta
    for lambda_per_trip, base_floor_pct, max_buy_pct, train_days, validate_days in grid:
        candidate = {
            **base_meta,
            "lambda_per_trip": lambda_per_trip,
            "base_floor_pct": base_floor_pct,
            "max_buy_pct": max_buy_pct,
            "train_days": train_days,
            "validate_days": validate_days,
        }
        score = score_meta_config(hourly_by_symbol, assets, candidate, initial_cash)
        if score > best_score:
            best_score = score
            best_meta = candidate

    best_meta["last_meta_at"] = now_utc.isoformat().replace("+00:00", "Z")
    config["meta"] = best_meta
    _append_csv(
        meta_history_path,
        {
            "Datetime": best_meta["last_meta_at"],
            "lambda_per_trip": best_meta["lambda_per_trip"],
            "base_floor_pct": best_meta["base_floor_pct"],
            "max_buy_pct": best_meta["max_buy_pct"],
            "train_days": best_meta["train_days"],
            "validate_days": best_meta["validate_days"],
            "simulation_score": best_score,
        },
        columns=META_HISTORY_COLUMNS,
    )
    return True


def write_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
