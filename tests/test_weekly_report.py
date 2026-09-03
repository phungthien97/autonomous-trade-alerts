from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.timezone_utils import should_send_weekly_now
from app.weekly_report import build_conclusion_report, build_report, build_weekly_report, weeks_since


def _write_fixture_state(root: Path, version: str, equity_rows: list[dict], experiment_start: str) -> None:
    state_dir = root / ("state" if version == "v1" else "state_v2")
    state_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "initial_cash": 1000.0,
        "experiment_start": experiment_start,
        "experiment_weeks": 10,
        "assets": [{"symbol": "AAPL", "enabled": True, "buy_rise_pct": 1.0, "sell_drop_pct": 1.5, "x_days": 20, "reopt_days": 5}],
    }
    if version == "v2":
        config["meta"] = {"last_meta_at": None, "meta_reopt_days": 28}
    (state_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (state_dir / "state.json").write_text("{}", encoding="utf-8")
    (state_dir / "trades.csv").write_text("Datetime,symbol,Action,Price\n", encoding="utf-8")
    equity = "Datetime,symbol,Close,Shares,Cash,Portfolio_Value,buy_rise_pct,sell_drop_pct\n"
    for row in equity_rows:
        equity += (
            f"{row['Datetime']},{row['symbol']},{row['Close']},{row['Shares']},"
            f"{row['Cash']},{row['Portfolio_Value']},{row['buy_rise_pct']},{row['sell_drop_pct']}\n"
        )
    (state_dir / "equity.csv").write_text(equity, encoding="utf-8")
    if version == "v2":
        (state_dir / "params_history.csv").write_text(
            "Datetime,symbol,x_days,buy_rise_pct,sell_drop_pct,train_final_value,validate_final_value,status,reject_reason\n",
            encoding="utf-8",
        )


def test_weeks_since() -> None:
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    assert weeks_since("2026-01-01T00:00:00Z", now=now) == 10


def test_weekly_report_contains_returns(tmp_path: Path) -> None:
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        {
            "Datetime": "2026-01-20T19:30:00+00:00",
            "symbol": "AAPL",
            "Close": 100,
            "Shares": 10,
            "Cash": 0,
            "Portfolio_Value": 1000,
            "buy_rise_pct": 1.0,
            "sell_drop_pct": 1.5,
        },
        {
            "Datetime": "2026-01-28T19:30:00+00:00",
            "symbol": "AAPL",
            "Close": 110,
            "Shares": 10,
            "Cash": 0,
            "Portfolio_Value": 1100,
            "buy_rise_pct": 1.0,
            "sell_drop_pct": 1.5,
        },
    ]
    _write_fixture_state(tmp_path, "v1", rows, "2026-01-01T00:00:00Z")
    _write_fixture_state(tmp_path, "v2", rows, "2026-01-01T00:00:00Z")
    report = build_weekly_report(project_root=tmp_path, now=now)
    assert "V1:" in report
    assert "V2:" in report
    assert "Leader since" in report


def test_week_9_weekly_format(tmp_path: Path) -> None:
    now = datetime(2026, 3, 8, tzinfo=timezone.utc)
    _write_fixture_state(tmp_path, "v1", [], "2026-01-01T00:00:00Z")
    _write_fixture_state(tmp_path, "v2", [], "2026-01-01T00:00:00Z")
    report = build_report(project_root=tmp_path, now=now)
    assert "Weekly Trading Bot Summary" in report
    assert "10-Week Experiment Conclusion" not in report


def test_week_10_conclusion_format(tmp_path: Path) -> None:
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _write_fixture_state(tmp_path, "v1", [], "2026-01-01T00:00:00Z")
    _write_fixture_state(tmp_path, "v2", [], "2026-01-01T00:00:00Z")
    report = build_conclusion_report(project_root=tmp_path, now=now)
    assert "Winner:" in report
    assert "10-Week Experiment Conclusion" in report


def test_should_send_weekly_only_saturday_10am_et() -> None:
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    assert should_send_weekly_now(datetime(2026, 3, 7, 10, 0, tzinfo=et)) is True
    assert should_send_weekly_now(datetime(2026, 3, 7, 11, 0, tzinfo=et)) is False
    assert should_send_weekly_now(datetime(2026, 3, 6, 10, 0, tzinfo=et)) is False


@patch("app.weekly_report.send_signal_email")
def test_send_flag_calls_email(mock_send, tmp_path: Path) -> None:
    from app.weekly_report import main
    import sys

    _write_fixture_state(tmp_path, "v1", [], "2026-01-01T00:00:00Z")
    _write_fixture_state(tmp_path, "v2", [], "2026-01-01T00:00:00Z")
    with patch.object(sys, "argv", ["weekly_report", "--send", "--force"]):
        with patch("app.weekly_report.build_report") as mock_build:
            mock_build.return_value = "test report"
            main()
    mock_send.assert_called_once()
