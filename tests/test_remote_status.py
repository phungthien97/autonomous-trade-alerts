import json
from datetime import datetime, timezone
from pathlib import Path

from app.remote.status import (
    last_cycle_age_minutes,
    load_live_status,
    load_paper_status,
    load_picker_status,
    next_picker_rank_at,
)


def test_load_live_status(tmp_path: Path) -> None:
    live = tmp_path / "state_live"
    live.mkdir()
    (live / "config.json").write_text(
        json.dumps(
            {
                "mode": "broker_paper",
                "symbols": ["AAPL", "MSFT"],
                "trading_enabled": True,
                "total_cash": 3000,
            }
        ),
        encoding="utf-8",
    )
    (live / "state.json").write_text(
        json.dumps(
            {
                "cash_usd": 2000.0,
                "assets": {
                    "AAPL": {"shares": 2.0, "cash": 0.0, "last_price": 100.0, "peak": 110, "trough": None},
                    "MSFT": {"shares": 0.0, "cash": 1000.0, "last_price": 400.0, "peak": None, "trough": 390},
                },
            }
        ),
        encoding="utf-8",
    )
    (live / "risk.json").write_text(
        json.dumps({"trading_enabled": True, "open_incident": None}),
        encoding="utf-8",
    )
    (live / "last_cycle.json").write_text(
        json.dumps(
            {
                "ok": True,
                "at_utc": "2026-10-17T20:00:00+00:00",
                "mode": "broker_paper",
                "price_source": "ibkr_rth_hourly",
                "rth_ok": False,
                "decisions": [{"symbol": "AAPL", "signal": "BUY"}],
            }
        ),
        encoding="utf-8",
    )
    status = load_live_status(live)
    assert status["mode"] == "broker_paper"
    assert status["trading_enabled"] is True
    assert status["cash_usd"] == 2000.0
    assert {p["symbol"] for p in status["positions"]} == {"AAPL", "MSFT"}
    assert status["last_cycle"]["price_source"] == "ibkr_rth_hourly"


def test_load_paper_status(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({"symbols": ["VOO"]}), encoding="utf-8")
    (state / "state.json").write_text(
        json.dumps(
            {
                "cash": 0.0,
                "portfolio_value": 1400.0,
                "last_run_at": "2026-10-05T00:00:00+00:00",
                "assets": {"VOO": {"shares": 1.0, "cash": 0.0, "last_price": 400}},
            }
        ),
        encoding="utf-8",
    )
    status = load_paper_status(state)
    assert status["exists"] is True
    assert status["portfolio_value"] == 1400.0
    assert status["positions"][0]["symbol"] == "VOO"


def test_load_picker_status_ranking_meta(tmp_path: Path) -> None:
    picker = tmp_path / "state_picker"
    runs = picker / "ranking_runs"
    runs.mkdir(parents=True)
    (picker / "active_selection.json").write_text(
        json.dumps(
            {
                "applied_at": "t",
                "run_id": "r1",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "buy_rise": 0.02,
                        "sell_drop": 0.04,
                        "exit_only": False,
                        "awaiting_first_buy": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (picker / "pending_selection.json").write_text(
        json.dumps(
            {
                "apply_after": "2026-10-20T13:30:00+00:00",
                "symbols": [{"symbol": "MSFT", "buy_rise": 0.01, "sell_drop": 0.03}],
            }
        ),
        encoding="utf-8",
    )
    (runs / "20261018_002339.json").write_text(
        json.dumps(
            {
                "run_id": "20261018_002339",
                "ok": True,
                "aborted": False,
                "dry_run": True,
                "selected": [{"symbol": "FICO"}, {"symbol": "COHR"}],
            }
        ),
        encoding="utf-8",
    )
    status = load_picker_status(picker)
    assert status["active"][0]["symbol"] == "AAPL"
    assert status["active"][0]["awaiting_first_buy"] is True
    assert status["pending_present"] is True
    assert status["pending_symbols"] == ["MSFT"]
    assert status["latest_run"]["run_id"] == "20261018_002339"
    assert status["latest_run"]["selected"] == ["FICO", "COHR"]
    assert status["latest_run"]["dry_run"] is True
    assert status.get("next_rank_at_utc")


def test_next_picker_rank_at_saturday_midnight_et() -> None:
    # Wednesday 2026-10-28 20:00 ET → next Sat 2026-10-31 00:00 ET
    now = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)  # Wed 20:00 EDT
    nxt = next_picker_rank_at(now)
    assert nxt.astimezone(timezone.utc).isoformat().startswith("2026-10-31T04:00:00")


def test_last_cycle_age_minutes() -> None:
    now = datetime(2026, 10, 17, 20, 10, tzinfo=timezone.utc)
    age = last_cycle_age_minutes({"at_utc": "2026-10-17T20:00:00+00:00"}, now=now)
    assert age == 10.0
