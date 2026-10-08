from datetime import datetime, timedelta, timezone

from app.broker import InMemoryBroker
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.control import ack_risk, disable_trading, enable_trading, live_status
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
