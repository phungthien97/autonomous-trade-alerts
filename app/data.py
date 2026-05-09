from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf


def hourly_limit_start_date() -> str:
    """Yahoo 1h candles are limited to roughly last 730 days."""
    return str((datetime.now(timezone.utc) - timedelta(days=729)).date())


def download_hourly(symbol: str, start: str, end: str) -> pd.DataFrame:
    df = yf.download(
        symbol,
        start=start,
        end=end,
        interval="60m",
        auto_adjust=False,
        progress=False,
        prepost=True,
        multi_level_index=False,
    )
    if df.empty:
        raise RuntimeError(f"No data downloaded for {symbol} {start} -> {end}")
    df = df.reset_index()
    df = df[["Datetime", "Open", "High", "Low", "Close", "Adj Close", "Volume"]].copy()
    df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
    df["TradeDate"] = df["Datetime"].dt.date
    return df.sort_values("Datetime").reset_index(drop=True)


def download_recent_hourly(symbol: str, lookback_days: int) -> pd.DataFrame:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = max(
        datetime.strptime(hourly_limit_start_date(), "%Y-%m-%d").date(),
        end - timedelta(days=lookback_days),
    )
    return download_hourly(symbol=symbol, start=str(start), end=str(end))
