from datetime import datetime, timedelta, timezone

from app.broker import InMemoryBroker
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.control import (
    ack_risk,
    disable_trading,
    enable_trading,
    live_status,
    set_daily_order_cap,
)
from app.live.config import load_live_config
from app.live_worker import run_live_once
from app.paths import LivePaths
from app.risk import RiskController


def test_two_hour_stop_blocks_worker(tmp_path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(symbols=["AAA"], assets=[SymbolParams("AAA")], trading_enabled=True),
    )
    risk = RiskController(paths.risk_path)
    start = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    risk.trigger("reject_storm", start)
    risk.tick(start + timedelta(hours=2))
    summary = run_live_once(
        paths,
        InMemoryBroker(1000.0, last_prices={"AAA": 100.0}),
        risk,
        __import__("app.audit", fromlist=["AuditLog"]).AuditLog(paths.audit_log_path),
        start + timedelta(hours=3),
        {"AAA": 100.0},
        {"AAA": "bar"},
    )
    assert summary["skipped"] == "trading_disabled"
    assert risk.trading_enabled is False


def test_controls_disable_ack_enable(tmp_path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(paths.config_path, LiveConfig())
    disable_trading(paths)
    assert live_status(paths)["trading_enabled"] is False
    enable_trading(paths)
    assert live_status(paths)["trading_enabled"] is True
    risk = RiskController(paths.risk_path)
    now = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    risk.trigger("max_orders", now)
    ack_risk(paths, now)
    assert live_status(paths)["incident"] is None


def test_set_daily_order_cap(tmp_path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(paths.config_path, LiveConfig(daily_order_cap=5))
    assert LiveConfig().daily_order_cap == 5
    assert set_daily_order_cap(paths, 15) == 15
    assert load_live_config(paths.config_path).daily_order_cap == 15
    assert live_status(paths)["daily_order_cap"] == 15
    try:
        set_daily_order_cap(paths, 0)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_per_symbol_order_cap_blocks_only_that_symbol(tmp_path) -> None:
    """Account-wide sum no longer gates; each ticker has its own daily cap."""
    import json
    from zoneinfo import ZoneInfo

    from app.audit import AuditLog
    from app.live.modes import TradingMode

    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(
            mode=TradingMode.broker_paper,
            symbols=["AAA", "BBB"],
            total_cash=20_000.0,
            daily_order_cap=2,
            assets=[
                SymbolParams("AAA", buy_rise_pct=1.0, sell_drop_pct=2.0),
                SymbolParams("BBB", buy_rise_pct=1.0, sell_drop_pct=2.0),
            ],
        ),
    )
    now = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    day = now.astimezone(ZoneInfo("America/Toronto")).date().isoformat()
    paths.state_path.write_text(
        json.dumps(
            {
                "cash_usd": 20_000.0,
                "orders_today": 2,
                "orders_today_by_symbol": {"AAA": 2, "BBB": 0},
                "orders_day": day,
                "assets": {
                    "AAA": {
                        "cash": 10_000.0,
                        "shares": 0.0,
                        "peak": None,
                        "trough": 100.0,
                    },
                    "BBB": {
                        "cash": 10_000.0,
                        "shares": 0.0,
                        "peak": None,
                        "trough": 100.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    broker = InMemoryBroker(20_000.0, last_prices={"AAA": 102.0, "BBB": 102.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    out = run_live_once(
        paths,
        broker,
        risk,
        audit,
        now,
        {"AAA": 102.0, "BBB": 102.0},
        {"AAA": "bar-a", "BBB": "bar-b"},
    )
    actions = out.get("actions") or []
    assert "AAA:order_cap" in actions
    assert any(a.startswith("BBB:") and a != "BBB:order_cap" for a in actions)
    assert broker.get_positions().get("BBB", 0) > 0
    assert broker.get_positions().get("AAA", 0) == 0
    assert out.get("daily_order_cap") == 2
