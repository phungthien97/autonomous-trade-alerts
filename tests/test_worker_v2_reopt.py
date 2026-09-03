from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.strategy import optimize_params
from app.worker import run_once


def _minimal_config_v2() -> dict:
    return {
        "initial_cash": 1000.0,
        "alerts_enabled": False,
        "experiment_start": "2026-01-01T00:00:00Z",
        "meta": {
            "last_meta_at": "2099-01-01T00:00:00Z",
            "meta_reopt_days": 28,
            "lambda_per_trip": 10.0,
            "base_floor_pct": 2.0,
            "max_buy_pct": 8.0,
            "train_days": 15,
            "validate_days": 5,
            "simulation_weeks": 8,
        },
        "assets": [
            {
                "symbol": "AAPL",
                "buy_rise_pct": 1.0,
                "sell_drop_pct": 1.5,
                "x_days": 20,
                "reopt_days": 0,
                "enabled": True,
            }
        ],
    }


def _minimal_state() -> dict:
    return {
        "cash": 0.0,
        "shares": 0.0,
        "peak": None,
        "trough": None,
        "last_price": 0.0,
        "last_action": "HOLD",
        "last_signal_reason": "No signal",
        "assets": {},
    }


def _hourly_df(prices: list[float], start: datetime | None = None, daily: bool = False) -> pd.DataFrame:
    start = start or datetime.now(timezone.utc) - timedelta(days=len(prices))
    rows = []
    for i, price in enumerate(prices):
        dt = start + (timedelta(days=i, hours=10) if daily else timedelta(hours=i))
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


def _bootstrap_v2(root: Path) -> None:
    state_dir = root / "state_v2"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text(json.dumps(_minimal_config_v2(), indent=2), encoding="utf-8")
    (state_dir / "state.json").write_text(json.dumps(_minimal_state(), indent=2), encoding="utf-8")
    (state_dir / "trades.csv").write_text(
        "Datetime,Action,Price,Shares_After,Cash_After,Portfolio_Value,buy_rise_pct,sell_drop_pct,Reason,symbol\n",
        encoding="utf-8",
    )
    (state_dir / "equity.csv").write_text(
        "Datetime,symbol,Close,Shares,Cash,Portfolio_Value,buy_rise_pct,sell_drop_pct\n",
        encoding="utf-8",
    )
    (state_dir / "params_history.csv").write_text(
        "Datetime,symbol,x_days,buy_rise_pct,sell_drop_pct,train_final_value,validate_final_value,status,reject_reason\n",
        encoding="utf-8",
    )
    (state_dir / "meta_history.csv").write_text(
        "Datetime,lambda_per_trip,base_floor_pct,max_buy_pct,train_days,validate_days,simulation_score\n",
        encoding="utf-8",
    )


@patch("app.worker.optimize_params_v2")
@patch("app.worker.download_hourly")
def test_worker_v2_reopt_applies(mock_download, mock_opt_v2, tmp_path: Path) -> None:
    _bootstrap_v2(tmp_path)
    uptrend = list(np.linspace(100, 140, 30))
    mock_download.return_value = _hourly_df(uptrend, daily=True)
    mock_opt_v2.return_value = (0.02, 0.03, 1100.0, True, "applied")

    run_once(version="v2", project_root=tmp_path)

    params = pd.read_csv(tmp_path / "state_v2" / "params_history.csv")
    assert not params.empty
    assert params.iloc[-1]["status"] == "applied"
    saved_config = json.loads((tmp_path / "state_v2" / "config.json").read_text(encoding="utf-8"))
    assert saved_config["assets"][0]["buy_rise_pct"] == 2.0


@patch("app.worker.optimize_params_v2")
@patch("app.worker.download_hourly")
def test_worker_v2_reopt_rejected(mock_download, mock_opt_v2, tmp_path: Path) -> None:
    _bootstrap_v2(tmp_path)
    prices = list(np.linspace(100, 120, 30))
    mock_download.return_value = _hourly_df(prices, daily=True)
    mock_opt_v2.return_value = (0.02, 0.02, 50.0, False, "holdout_rejected")

    config = json.loads((tmp_path / "state_v2" / "config.json").read_text(encoding="utf-8"))
    config["assets"][0]["buy_rise_pct"] = 3.0
    config["assets"][0]["sell_drop_pct"] = 3.0
    (tmp_path / "state_v2" / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    run_once(version="v2", project_root=tmp_path)

    params = pd.read_csv(tmp_path / "state_v2" / "params_history.csv")
    assert params.iloc[-1]["status"] == "rejected"
    saved_config = json.loads((tmp_path / "state_v2" / "config.json").read_text(encoding="utf-8"))
    assert saved_config["assets"][0]["buy_rise_pct"] == 3.0


@patch("app.worker.optimize_params")
@patch("app.worker.download_hourly")
def test_worker_v1_uses_optimize_params_only(mock_download, mock_opt, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    config = _minimal_config_v2()
    config.pop("meta", None)
    config["assets"][0]["reopt_days"] = 0
    (state_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (state_dir / "state.json").write_text(json.dumps(_minimal_state(), indent=2), encoding="utf-8")
    (state_dir / "trades.csv").write_text(
        "Datetime,Action,Price,Shares_After,Cash_After,Portfolio_Value,buy_rise_pct,sell_drop_pct,Reason,symbol\n",
        encoding="utf-8",
    )
    (state_dir / "equity.csv").write_text(
        "Datetime,symbol,Close,Shares,Cash,Portfolio_Value,buy_rise_pct,sell_drop_pct\n",
        encoding="utf-8",
    )
    (state_dir / "params_history.csv").write_text(
        "Datetime,symbol,x_days,buy_rise_pct,sell_drop_pct,train_final_value\n",
        encoding="utf-8",
    )
    mock_download.return_value = _hourly_df(list(np.linspace(100, 110, 80)))
    mock_opt.return_value = (0.01, 0.02, 1050.0)

    run_once(version="v1", project_root=tmp_path)
    mock_opt.assert_called_once()
