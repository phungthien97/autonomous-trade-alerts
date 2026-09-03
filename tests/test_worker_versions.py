from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.worker import run_once


def _minimal_config() -> dict:
    return {
        "initial_cash": 1000.0,
        "buy_rise_pct": 1.0,
        "sell_drop_pct": 1.5,
        "x_days": 20,
        "reopt_days": 5,
        "alerts_enabled": False,
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


def _mock_hourly_df(price: float = 150.0, bars: int = 30) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(bars):
        dt = now - timedelta(hours=bars - i)
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


def _bootstrap_state_dir(root: Path, version: str) -> None:
    state_dir = root / ("state" if version == "v1" else "state_v2")
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text(json.dumps(_minimal_config(), indent=2), encoding="utf-8")
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


def _dir_snapshot(state_dir: Path) -> dict[str, str]:
    if not state_dir.exists():
        return {}
    return {
        str(path.relative_to(state_dir)): path.read_text(encoding="utf-8")
        for path in sorted(state_dir.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def isolated_project(tmp_path: Path) -> Path:
    _bootstrap_state_dir(tmp_path, "v1")
    _bootstrap_state_dir(tmp_path, "v2")
    return tmp_path


@patch("app.worker.download_hourly")
@patch("app.worker.send_signal_email")
def test_worker_v1_does_not_touch_state_v2(
    mock_send_email,
    mock_download,
    isolated_project: Path,
) -> None:
    mock_download.return_value = _mock_hourly_df()
    v2_before = _dir_snapshot(isolated_project / "state_v2")

    run_once(version="v1", project_root=isolated_project)

    v2_after = _dir_snapshot(isolated_project / "state_v2")
    assert v2_after == v2_before
    assert (isolated_project / "state" / "state.json").exists()
    mock_send_email.assert_not_called()


@patch("app.worker.download_hourly")
@patch("app.worker.send_signal_email")
def test_worker_v2_does_not_touch_state(
    mock_send_email,
    mock_download,
    isolated_project: Path,
) -> None:
    mock_download.return_value = _mock_hourly_df()
    v1_before = _dir_snapshot(isolated_project / "state")

    run_once(version="v2", project_root=isolated_project)

    v1_after = _dir_snapshot(isolated_project / "state")
    assert v1_after == v1_before
    assert (isolated_project / "state_v2" / "state.json").exists()
    mock_send_email.assert_not_called()


@patch("app.worker.download_hourly")
def test_worker_v2_writes_only_under_state_v2(mock_download, isolated_project: Path) -> None:
    mock_download.return_value = _mock_hourly_df()

    run_once(version="v2", project_root=isolated_project)

    state = json.loads((isolated_project / "state_v2" / "state.json").read_text(encoding="utf-8"))
    assert state.get("last_run_at") is not None
    assert "AAPL" in state["assets"]
    equity = (isolated_project / "state_v2" / "equity.csv").read_text(encoding="utf-8")
    assert "AAPL" in equity
