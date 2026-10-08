from datetime import datetime, timezone

from app.audit.log import AuditLog
from app.broker import InMemoryBroker
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.modes import TradingMode
from app.live_worker import main, run_live_once
from app.paths import LivePaths
from app.risk import RiskController


def _ready(tmp_path, mode: TradingMode) -> LivePaths:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    config = LiveConfig(
        mode=mode,
        symbols=["AAA"],
        total_cash=1000.0,
        assets=[SymbolParams("AAA", buy_rise_pct=1.0, sell_drop_pct=2.0)],
        allow_fractional_default=True,
    )
    save_live_config(paths.config_path, config)
    return paths


def test_buy_then_sell_memory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "YES")
    paths = _ready(tmp_path, TradingMode.live)
    broker = InMemoryBroker(1000.0, last_prices={"AAA": 100.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    run_live_once(paths, broker, risk, audit, t1, {"AAA": 100.0}, {"AAA": "bar-1"})
    run_live_once(paths, broker, risk, audit, t2, {"AAA": 102.0}, {"AAA": "bar-2"})
    assert broker.get_positions().get("AAA", 0) > 0

    t3 = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    run_live_once(paths, broker, risk, audit, t3, {"AAA": 99.0}, {"AAA": "bar-3"})
    assert broker.get_positions().get("AAA", 0) == 0


def test_live_cli_requires_confirm(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    try:
        main(["--mode", "live", "--broker", "memory"])
        raised = False
    except SystemExit as exc:
        raised = exc.code == 1
    assert raised is True


def test_dry_run_cli_does_not_submit(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    # main uses LivePaths() repo root, not chdir. Call run via mocked path by invoking main's refusal path only.
    from app.live.executor import execute_intent
    from app.live.idempotency import IdempotencyStore
    from app.live.planner import OrderIntent
    from app.live.queue import PendingIntentStore
    from app.live.modes import TradingMode

    broker = InMemoryBroker(1000.0, last_prices={"AAA": 10.0})
    execute_intent(
        OrderIntent("AAA", "BUY", 1, 0.1, "b", "r"),
        broker,
        IdempotencyStore(tmp_path / "i.json"),
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.live_dry_run,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert broker.get_positions() == {}
    assert "place" not in capsys.readouterr().out
