import json
from pathlib import Path

import pandas as pd

from app.worker import run_once


def _hourly_df(closes: list[float]) -> pd.DataFrame:
    start = pd.Timestamp("2026-09-01T14:30:00Z")
    rows = []
    for i, px in enumerate(closes):
        ts = start + pd.Timedelta(hours=i)
        rows.append({"Datetime": ts, "Close": px, "TradeDate": ts.tz_convert(None).date()})
    return pd.DataFrame(rows)


def test_exit_only_suppresses_buy(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps(
            {
                "initial_cash": 1000.0,
                "alerts_enabled": False,
                "assets": [
                    {
                        "symbol": "AAA",
                        "buy_rise_pct": 1.0,
                        "sell_drop_pct": 50.0,
                        "x_days": 5,
                        "reopt_days": 30,
                        "enabled": True,
                        "exit_only": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "assets": {
                    "AAA": {
                        "cash": 1000.0,
                        "shares": 0.0,
                        "peak": None,
                        "trough": 100.0,
                        "initial_cash": 1000.0,
                        "exit_only": True,
                        "last_bar_at": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_download(symbol: str, start: str, end: str) -> pd.DataFrame:
        return _hourly_df([100.0, 99.0, 101.0])

    monkeypatch.setattr("app.worker.download_hourly", fake_download)
    monkeypatch.setattr("app.worker.hourly_limit_start_date", lambda: "2020-01-01")
    monkeypatch.setattr(
        "app.worker._reoptimize_v1",
        lambda **kwargs: (0.01, 0.50, False),
    )
    run_once(version="v1", project_root=tmp_path)

    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["assets"]["AAA"]["shares"] == 0.0
    assert state["assets"]["AAA"]["exit_only"] is True
    assert "exit_only" in state["assets"]["AAA"]["last_signal_reason"]
