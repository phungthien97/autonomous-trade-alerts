from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.meta_optimizer import run_meta_if_due


def _hourly_df(prices: list[float], start: datetime | None = None) -> pd.DataFrame:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, price in enumerate(prices):
        dt = start + timedelta(hours=i)
        rows.append(
            {
                "Datetime": dt,
                "Open": price,
                "High": price,
                "Low": price,
                "Close": price,
                "Adj Close": price,
                "Volume": 1000,
                "TradeDate": dt.date(),
            }
        )
    return pd.DataFrame(rows)


def _config() -> dict:
    return {
        "initial_cash": 1000.0,
        "assets": [
            {
                "symbol": "AAPL",
                "buy_rise_pct": 1.0,
                "sell_drop_pct": 1.5,
                "x_days": 20,
                "reopt_days": 5,
                "enabled": True,
            }
        ],
        "meta": {
            "last_meta_at": "2026-01-01T00:00:00Z",
            "meta_reopt_days": 28,
            "lambda_per_trip": 10.0,
            "base_floor_pct": 2.0,
            "max_buy_pct": 8.0,
            "train_days": 15,
            "validate_days": 5,
            "simulation_weeks": 8,
        },
    }


def test_meta_not_due_skips(tmp_path: Path) -> None:
    config = _config()
    meta_path = tmp_path / "meta_history.csv"
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    hourly = {"AAPL": _hourly_df(list(np.linspace(100, 120, 200)))}
    changed = run_meta_if_due(config, meta_path, now, hourly)
    assert changed is False
    assert not meta_path.exists()


def test_meta_due_updates_config(tmp_path: Path) -> None:
    config = _config()
    config["meta"]["last_meta_at"] = None
    meta_path = tmp_path / "meta_history.csv"
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    hourly = {"AAPL": _hourly_df(list(np.linspace(100, 130, 400)))}
    changed = run_meta_if_due(config, meta_path, now, hourly)
    assert changed is True
    assert config["meta"]["last_meta_at"] is not None
    assert "lambda_per_trip" in config["meta"]


def test_meta_logs_history(tmp_path: Path) -> None:
    config = _config()
    config["meta"]["last_meta_at"] = None
    meta_path = tmp_path / "meta_history.csv"
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    hourly = {"AAPL": _hourly_df(list(np.linspace(100, 130, 400)))}
    run_meta_if_due(config, meta_path, now, hourly)
    hist = pd.read_csv(meta_path)
    assert len(hist) == 1
    assert "simulation_score" in hist.columns
