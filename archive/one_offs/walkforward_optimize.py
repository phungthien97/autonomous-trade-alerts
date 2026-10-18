import itertools
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


INITIAL_CASH = 1000.0
REOPT_DAYS = 5
BUY_GRID = np.arange(0.01, 0.1501, 0.005)   # 1.0% to 15.0%
SELL_GRID = np.arange(0.01, 0.1501, 0.005)  # 1.0% to 15.0%
X_CANDIDATES = [20, 40, 60, 90, 120, 180]
SYMBOL = "ZSP.TO"


@dataclass
class StrategyState:
    cash: float
    shares: float
    peak: Optional[float]
    trough: Optional[float]


def download_hourly(symbol: str, start: str, end: str) -> pd.DataFrame:
    df = yf.download(
        symbol,
        start=start,
        end=end,
        interval="60m",
        auto_adjust=False,
        progress=False,
        prepost=False,
        multi_level_index=False,
    )
    if df.empty:
        raise RuntimeError(f"No data downloaded for {symbol} {start} -> {end}")
    df = df.reset_index()
    cols = ["Datetime", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    df = df[cols].copy()
    df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
    df["TradeDate"] = df["Datetime"].dt.date
    return df.sort_values("Datetime").reset_index(drop=True)


def run_fixed_params(prices: np.ndarray, buy_rise: float, sell_drop: float, initial_cash: float = INITIAL_CASH) -> float:
    if len(prices) == 0:
        return initial_cash
    cash = initial_cash
    shares = cash / prices[0]
    cash = 0.0
    peak = prices[0]
    trough = None
    for p in prices[1:]:
        if shares > 0:
            peak = max(peak, p)
            if p <= peak * (1 - sell_drop):
                cash = shares * p
                shares = 0.0
                trough = p
                peak = None
        else:
            trough = p if trough is None else min(trough, p)
            if p >= trough * (1 + buy_rise):
                shares = cash / p
                cash = 0.0
                peak = p
                trough = None
    return cash + shares * prices[-1]


def optimize_params(train_prices: np.ndarray) -> tuple[float, float, float]:
    best_val = -1.0
    best_pair = (BUY_GRID[0], SELL_GRID[0])
    for buy_rise, sell_drop in itertools.product(BUY_GRID, SELL_GRID):
        final_val = run_fixed_params(train_prices, buy_rise=buy_rise, sell_drop=sell_drop, initial_cash=INITIAL_CASH)
        if final_val > best_val:
            best_val = final_val
            best_pair = (buy_rise, sell_drop)
    return best_pair[0], best_pair[1], best_val


def initialize_live_state(df_period: pd.DataFrame) -> tuple[StrategyState, list[dict]]:
    first_price = float(df_period.iloc[0]["Close"])
    first_time = df_period.iloc[0]["Datetime"]
    state = StrategyState(cash=0.0, shares=INITIAL_CASH / first_price, peak=first_price, trough=None)
    events = [
        {
            "Datetime": first_time,
            "Action": "BUY",
            "Price": first_price,
            "Shares_After": state.shares,
            "Cash_After": state.cash,
            "Portfolio_Value": INITIAL_CASH,
            "buy_rise_pct": np.nan,
            "sell_drop_pct": np.nan,
            "Reason": "Initial full allocation",
        }
    ]
    return state, events


def apply_block(
    block_df: pd.DataFrame,
    state: StrategyState,
    buy_rise: float,
    sell_drop: float,
) -> list[dict]:
    events = []
    for _, row in block_df.iterrows():
        t = row["Datetime"]
        p = float(row["Close"])
        if state.shares > 0:
            state.peak = max(state.peak, p)
            if p <= state.peak * (1 - sell_drop):
                state.cash = state.shares * p
                state.shares = 0.0
                state.trough = p
                state.peak = None
                events.append(
                    {
                        "Datetime": t,
                        "Action": "SELL",
                        "Price": p,
                        "Shares_After": state.shares,
                        "Cash_After": state.cash,
                        "Portfolio_Value": state.cash,
                        "buy_rise_pct": buy_rise * 100.0,
                        "sell_drop_pct": sell_drop * 100.0,
                        "Reason": "Price dropped from rolling peak threshold",
                    }
                )
        else:
            state.trough = p if state.trough is None else min(state.trough, p)
            if p >= state.trough * (1 + buy_rise):
                state.shares = state.cash / p
                state.cash = 0.0
                state.peak = p
                state.trough = None
                events.append(
                    {
                        "Datetime": t,
                        "Action": "BUY",
                        "Price": p,
                        "Shares_After": state.shares,
                        "Cash_After": state.cash,
                        "Portfolio_Value": state.shares * p,
                        "buy_rise_pct": buy_rise * 100.0,
                        "sell_drop_pct": sell_drop * 100.0,
                        "Reason": "Price rose from rolling trough threshold",
                    }
                )
    return events


def walkforward(
    trade_df: pd.DataFrame,
    history_df: pd.DataFrame,
    x_days: int,
    reopt_days: int = REOPT_DAYS,
) -> tuple[float, pd.DataFrame, pd.DataFrame]:
    unique_days_trade = sorted(trade_df["TradeDate"].unique())
    unique_days_history = sorted(history_df["TradeDate"].unique())
    day_to_idx_history = {d: i for i, d in enumerate(unique_days_history)}

    live_state, trade_events = initialize_live_state(trade_df)
    param_rows = []

    i = 0
    while i < len(unique_days_trade):
        block_days = unique_days_trade[i : i + reopt_days]
        block_start = block_days[0]
        hist_idx = day_to_idx_history[block_start]
        train_end_idx = hist_idx - 1
        if train_end_idx < 1:
            i += reopt_days
            continue
        train_start_idx = max(0, train_end_idx - x_days + 1)
        train_days = unique_days_history[train_start_idx : train_end_idx + 1]

        train_df = history_df[history_df["TradeDate"].isin(train_days)]
        train_prices = train_df["Close"].astype(float).to_numpy()
        buy_rise, sell_drop, train_best_val = optimize_params(train_prices)

        param_rows.append(
            {
                "Block_Start": pd.Timestamp(block_start),
                "Block_End": pd.Timestamp(block_days[-1]),
                "Train_Days_Used": len(train_days),
                "buy_rise_pct": buy_rise * 100.0,
                "sell_drop_pct": sell_drop * 100.0,
                "Train_Final_Value": train_best_val,
            }
        )

        block_df = trade_df[trade_df["TradeDate"].isin(block_days)]
        trade_events.extend(apply_block(block_df, live_state, buy_rise, sell_drop))
        i += reopt_days

    last_price = float(trade_df.iloc[-1]["Close"])
    final_val = live_state.cash + live_state.shares * last_price
    trade_events.append(
        {
            "Datetime": trade_df.iloc[-1]["Datetime"],
            "Action": "FINAL_MARK_TO_MARKET",
            "Price": last_price,
            "Shares_After": live_state.shares,
            "Cash_After": live_state.cash,
            "Portfolio_Value": final_val,
            "buy_rise_pct": np.nan,
            "sell_drop_pct": np.nan,
            "Reason": "Final valuation at last available bar",
        }
    )
    return final_val, pd.DataFrame(trade_events), pd.DataFrame(param_rows)


def main() -> None:
    min_start_dt = (datetime.now(timezone.utc) - timedelta(days=729)).date()
    requested_2024_start = pd.Timestamp("2024-01-01").date()
    effective_2024_start = max(requested_2024_start, min_start_dt)

    data_2024 = download_hourly(SYMBOL, str(effective_2024_start), "2025-01-01")
    data_2025 = download_hourly(SYMBOL, "2025-01-01", "2026-01-01")
    all_data = pd.concat([data_2024, data_2025], ignore_index=True).sort_values("Datetime").reset_index(drop=True)

    x_selection_rows = []
    for x in X_CANDIDATES:
        final_2024, _, params_2024 = walkforward(
            trade_df=data_2024,
            history_df=data_2024,
            x_days=x,
            reopt_days=REOPT_DAYS,
        )
        x_selection_rows.append(
            {
                "x_days": x,
                "final_value_2024": final_2024,
                "return_pct_2024": (final_2024 / INITIAL_CASH - 1.0) * 100.0,
                "reopt_blocks_2024": len(params_2024),
            }
        )

    x_df = pd.DataFrame(x_selection_rows).sort_values("final_value_2024", ascending=False).reset_index(drop=True)
    best_x = int(x_df.iloc[0]["x_days"])

    final_2025, events_2025, params_2025 = walkforward(
        trade_df=data_2025,
        history_df=all_data,
        x_days=best_x,
        reopt_days=REOPT_DAYS,
    )

    first_2025_close = float(data_2025.iloc[0]["Close"])
    last_2025_close = float(data_2025.iloc[-1]["Close"])
    buy_hold_2025 = (INITIAL_CASH / first_2025_close) * last_2025_close

    x_df.to_csv("zsp_to_2024_x_selection_walkforward.csv", index=False)
    params_2025.to_csv("zsp_to_2025_walkforward_params.csv", index=False)
    events_2025.to_csv("zsp_to_2025_walkforward_trades.csv", index=False)

    summary = pd.DataFrame(
        [
            {
                "symbol": SYMBOL,
                "initial_cash": INITIAL_CASH,
                "reopt_days": REOPT_DAYS,
                "best_x_days_from_2024": best_x,
                "final_value_2025_walkforward": final_2025,
                "return_pct_2025_walkforward": (final_2025 / INITIAL_CASH - 1.0) * 100.0,
                "buy_hold_value_2025": buy_hold_2025,
                "buy_hold_return_pct_2025": (buy_hold_2025 / INITIAL_CASH - 1.0) * 100.0,
                "trade_event_rows_2025": len(events_2025),
                "param_blocks_2025": len(params_2025),
            }
        ]
    )
    summary.to_csv("zsp_walkforward_summary.csv", index=False)

    print(f"effective_2024_start={effective_2024_start}")
    print(f"best_x_days={best_x}")
    print(f"walkforward_final_2025={final_2025:.6f}")
    print(f"walkforward_return_pct_2025={(final_2025 / INITIAL_CASH - 1.0) * 100.0:.6f}")
    print(f"buy_hold_2025={buy_hold_2025:.6f}")
    print(f"buy_hold_return_pct_2025={(buy_hold_2025 / INITIAL_CASH - 1.0) * 100.0:.6f}")
    print("files=zsp_to_2024_x_selection_walkforward.csv,zsp_to_2025_walkforward_params.csv,zsp_to_2025_walkforward_trades.csv,zsp_walkforward_summary.csv")


if __name__ == "__main__":
    main()
