from datetime import datetime, timezone

from app.audit import AuditLog
from app.broker import InMemoryBroker
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.modes import TradingMode
from app.live_worker import run_live_once
from app.paths import LivePaths
from app.risk import RiskController


def test_memory_buy_sell_idempotent(tmp_path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(
            mode=TradingMode.broker_paper,
            symbols=["AAA"],
            total_cash=1000.0,
            assets=[SymbolParams("AAA", buy_rise_pct=1.0, sell_drop_pct=2.0)],
        ),
    )
    broker = InMemoryBroker(1000.0, last_prices={"AAA": 100.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    run_live_once(paths, broker, risk, audit, t1, {"AAA": 100.0}, {"AAA": "bar-1"})
    run_live_once(paths, broker, risk, audit, t2, {"AAA": 102.0}, {"AAA": "bar-2"})
    assert broker.get_positions().get("AAA", 0) > 0
    run_live_once(paths, broker, risk, audit, t3, {"AAA": 99.0}, {"AAA": "bar-3"})
    # Flat after selling below the 102 buy. Cash is the round-trip proceeds, not the starting 1000.
    assert broker.get_positions().get("AAA", 0) == 0
    cash = broker.get_account_snapshot().cash_usd
    assert 900 < cash < 1000
    assert risk.trading_enabled is True
    events = [row["event_type"] for row in audit.read_all()]
    assert "fill" in events or "order_submitted" in events
    cash_after = broker.get_account_snapshot().cash_usd
    run_live_once(paths, broker, risk, audit, t3, {"AAA": 99.0}, {"AAA": "bar-3"})
    assert broker.get_account_snapshot().cash_usd == cash_after
    run_live_once(paths, broker, risk, audit, t2, {"AAA": 102.0}, {"AAA": "bar-2"})
    assert broker.get_account_snapshot().cash_usd == cash_after
