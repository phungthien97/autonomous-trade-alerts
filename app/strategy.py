from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


DEFAULT_BUY_GRID = np.arange(0.01, 0.1501, 0.005)
DEFAULT_SELL_GRID = np.arange(0.01, 0.1501, 0.005)


@dataclass
class StrategyState:
    cash: float
    shares: float
    peak: Optional[float]
    trough: Optional[float]


def portfolio_value(state: StrategyState, price: float) -> float:
    return state.cash + (state.shares * price)


def step_signal(
    state: StrategyState,
    price: float,
    buy_rise: float,
    sell_drop: float,
) -> tuple[Optional[str], str]:
    if state.shares > 0:
        state.peak = max(float(state.peak), price)
        if price <= float(state.peak) * (1 - sell_drop):
            state.cash = state.shares * price
            state.shares = 0.0
            state.trough = price
            state.peak = None
            return "SELL", "Price dropped from rolling peak threshold"
    else:
        state.trough = price if state.trough is None else min(float(state.trough), price)
        if price >= float(state.trough) * (1 + buy_rise):
            state.shares = state.cash / price
            state.cash = 0.0
            state.peak = price
            state.trough = None
            return "BUY", "Price rose from rolling trough threshold"
    return None, "No signal"


def run_fixed_params(
    prices: np.ndarray,
    buy_rise: float,
    sell_drop: float,
    initial_cash: float,
) -> float:
    if len(prices) == 0:
        return initial_cash
    state = StrategyState(cash=0.0, shares=initial_cash / float(prices[0]), peak=float(prices[0]), trough=None)
    for p in prices[1:]:
        step_signal(state, float(p), buy_rise=buy_rise, sell_drop=sell_drop)
    return portfolio_value(state, float(prices[-1]))


def optimize_params(
    train_prices: np.ndarray,
    initial_cash: float,
    buy_grid: np.ndarray = DEFAULT_BUY_GRID,
    sell_grid: np.ndarray = DEFAULT_SELL_GRID,
) -> tuple[float, float, float]:
    best_val = -1.0
    best_pair = (float(buy_grid[0]), float(sell_grid[0]))
    for buy_rise, sell_drop in itertools.product(buy_grid, sell_grid):
        value = run_fixed_params(
            prices=train_prices,
            buy_rise=float(buy_rise),
            sell_drop=float(sell_drop),
            initial_cash=initial_cash,
        )
        if value > best_val:
            best_val = value
            best_pair = (float(buy_rise), float(sell_drop))
    return best_pair[0], best_pair[1], best_val


def count_round_trips(
    prices: np.ndarray,
    buy_rise: float,
    sell_drop: float,
    initial_cash: float,
) -> int:
    if len(prices) < 2:
        return 0
    state = StrategyState(
        cash=0.0,
        shares=initial_cash / float(prices[0]),
        peak=float(prices[0]),
        trough=None,
    )
    trips = 0
    for price in prices[1:]:
        action, _ = step_signal(state, float(price), buy_rise=buy_rise, sell_drop=sell_drop)
        if action == "SELL":
            trips += 1
    return trips


def symbol_floor_pct(meta: dict, symbol_vol: float, median_vol: float) -> float:
    base_floor = float(meta.get("base_floor_pct", 2.0)) / 100.0
    min_floor = float(meta.get("min_floor_pct", 1.0)) / 100.0
    max_floor = float(meta.get("max_floor_pct", 5.0)) / 100.0
    ratio = 1.0 if median_vol <= 0 else symbol_vol / median_vol
    return float(min(max(base_floor * ratio, min_floor), max_floor))


def build_constrained_grid(
    meta: dict,
    symbol_vol: float,
    median_vol: float,
) -> list[tuple[float, float]]:
    floor = symbol_floor_pct(meta, symbol_vol, median_vol)
    max_buy = float(meta.get("max_buy_pct", 8.0)) / 100.0
    pairs: list[tuple[float, float]] = []
    for buy_rise in DEFAULT_BUY_GRID:
        buy = float(buy_rise)
        if buy < floor or buy > max_buy:
            continue
        min_sell = buy / 2.0
        for sell_drop in DEFAULT_SELL_GRID:
            sell = float(sell_drop)
            if sell >= min_sell:
                pairs.append((buy, sell))
    return pairs


def score_params(
    prices: np.ndarray,
    buy_rise: float,
    sell_drop: float,
    initial_cash: float,
    lambda_per_trip: float,
) -> float:
    final_value = run_fixed_params(prices, buy_rise=buy_rise, sell_drop=sell_drop, initial_cash=initial_cash)
    trips = count_round_trips(prices, buy_rise=buy_rise, sell_drop=sell_drop, initial_cash=initial_cash)
    return final_value - (lambda_per_trip * trips)


def optimize_params_v2(
    train_prices: np.ndarray,
    validate_prices: np.ndarray,
    current: tuple[float, float],
    meta: dict,
    initial_cash: float,
    symbol_vol: float,
    median_vol: float,
) -> tuple[float, float, float, bool, str]:
    current_buy, current_sell = current
    grid = build_constrained_grid(meta, symbol_vol=symbol_vol, median_vol=median_vol)
    if not grid:
        return current_buy, current_sell, 0.0, False, "no_valid_grid"

    lambda_per_trip = float(meta.get("lambda_per_trip", 10.0))
    best_score = float("-inf")
    best_pair = (current_buy, current_sell)
    for buy_rise, sell_drop in grid:
        train_score = score_params(
            train_prices,
            buy_rise=buy_rise,
            sell_drop=sell_drop,
            initial_cash=initial_cash,
            lambda_per_trip=lambda_per_trip,
        )
        if train_score > best_score:
            best_score = train_score
            best_pair = (buy_rise, sell_drop)

    current_validate_score = score_params(
        validate_prices,
        buy_rise=current_buy,
        sell_drop=current_sell,
        initial_cash=initial_cash,
        lambda_per_trip=lambda_per_trip,
    )
    candidate_validate_score = score_params(
        validate_prices,
        buy_rise=best_pair[0],
        sell_drop=best_pair[1],
        initial_cash=initial_cash,
        lambda_per_trip=lambda_per_trip,
    )
    if candidate_validate_score <= current_validate_score:
        return current_buy, current_sell, candidate_validate_score, False, "holdout_rejected"

    return best_pair[0], best_pair[1], candidate_validate_score, True, "applied"


def select_best_x_days(
    baseline_df: pd.DataFrame,
    x_candidates: list[int],
    reopt_days: int,
    initial_cash: float,
) -> pd.DataFrame:
    unique_days = sorted(baseline_df["TradeDate"].unique())
    rows: list[dict] = []
    for x_days in x_candidates:
        state = StrategyState(
            cash=0.0,
            shares=initial_cash / float(baseline_df.iloc[0]["Close"]),
            peak=float(baseline_df.iloc[0]["Close"]),
            trough=None,
        )
        i = 0
        blocks = 0
        while i < len(unique_days):
            block_days = unique_days[i : i + reopt_days]
            train_end = max(0, i - 1)
            train_start = max(0, train_end - x_days + 1)
            train_days = unique_days[train_start : train_end + 1]
            if len(train_days) < 2:
                i += reopt_days
                continue
            train_prices = baseline_df[baseline_df["TradeDate"].isin(train_days)]["Close"].astype(float).to_numpy()
            buy_rise, sell_drop, _ = optimize_params(train_prices=train_prices, initial_cash=initial_cash)
            block_df = baseline_df[baseline_df["TradeDate"].isin(block_days)]
            for _, row in block_df.iterrows():
                step_signal(state, float(row["Close"]), buy_rise=buy_rise, sell_drop=sell_drop)
            blocks += 1
            i += reopt_days
        last_price = float(baseline_df.iloc[-1]["Close"])
        final_val = portfolio_value(state, last_price)
        rows.append(
            {
                "x_days": x_days,
                "final_value_2024": final_val,
                "return_pct_2024": (final_val / initial_cash - 1.0) * 100.0,
                "reopt_blocks_2024": blocks,
            }
        )
    return pd.DataFrame(rows).sort_values("final_value_2024", ascending=False).reset_index(drop=True)
