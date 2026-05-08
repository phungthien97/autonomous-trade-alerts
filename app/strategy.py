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
