from datetime import datetime, timezone

from app.audit.log import AuditLog
from app.broker import InMemoryBroker
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.modes import TradingMode
from app.live_worker import run_live_once
from app.paths import LivePaths, PickerPaths
from app.picker.active import ActiveSelection, ActiveSymbol, save_active
from app.risk import RiskController


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "YES")
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(
            mode=TradingMode.live,
            symbols=["AAA"],
            total_cash=1000.0,
            assets=[SymbolParams("AAA", buy_rise_pct=1.0, sell_drop_pct=50.0)],
            allow_fractional_default=True,
        ),
    )
    return paths


def test_exit_only_blocks_buy(tmp_path, monkeypatch) -> None:
    paths = _setup(tmp_path, monkeypatch)
    picker = PickerPaths(project_root=tmp_path)
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="t",
            run_id="r",
            symbols=[ActiveSymbol("AAA", 0.01, 0.5, exit_only=True)],
        ),
    )
    broker = InMemoryBroker(1000.0, last_prices={"AAA": 100.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    run_live_once(paths, broker, risk, audit, t1, {"AAA": 100.0}, {"AAA": "b1"})
    out = run_live_once(paths, broker, risk, audit, t2, {"AAA": 102.0}, {"AAA": "b2"})
    assert broker.get_positions().get("AAA", 0) == 0
    assert out["decisions"][0]["gate"] == "exit_only"


def test_sma_gate_blocks_awaiting_first_buy(tmp_path, monkeypatch) -> None:
    paths = _setup(tmp_path, monkeypatch)
    picker = PickerPaths(project_root=tmp_path)
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="t",
            run_id="r",
            symbols=[ActiveSymbol("AAA", 0.01, 0.5, awaiting_first_buy=True)],
        ),
    )
    broker = InMemoryBroker(1000.0, last_prices={"AAA": 100.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    # History below SMA path: flat 20 then dip bounce still under prior mean if we use declining series
    history = [110.0] * 19 + [100.0]
    run_live_once(paths, broker, risk, audit, t1, {"AAA": 100.0}, {"AAA": "b1"}, closes_by_symbol={"AAA": history})
    out = run_live_once(
        paths,
        broker,
        risk,
        audit,
        t2,
        {"AAA": 101.5},
        {"AAA": "b2"},
        closes_by_symbol={"AAA": history + [101.5]},
    )
    assert broker.get_positions().get("AAA", 0) == 0
    assert out["decisions"][0]["gate"] == "sma20_gate"
    reason = out["decisions"][0]["signal_reason"]
    assert "20-hour average" in reason
    assert "$101.50" in reason
    assert out["decisions"][0]["plan"] == "waiting on 20-hour average"


def test_sma_gate_fail_closed_without_close_history(tmp_path, monkeypatch) -> None:
    """Empty closes_by_symbol must block first buy (production used to omit history)."""
    paths = _setup(tmp_path, monkeypatch)
    picker = PickerPaths(project_root=tmp_path)
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="t",
            run_id="r",
            symbols=[ActiveSymbol("AAA", 0.01, 0.5, awaiting_first_buy=True)],
        ),
    )
    broker = InMemoryBroker(1000.0, last_prices={"AAA": 100.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    run_live_once(paths, broker, risk, audit, t1, {"AAA": 100.0}, {"AAA": "b1"})
    out = run_live_once(paths, broker, risk, audit, t2, {"AAA": 102.0}, {"AAA": "b2"})
    assert broker.get_positions().get("AAA", 0) == 0
    assert out["decisions"][0]["gate"] == "sma20_gate"
    assert "need 20 hourly closes" in out["decisions"][0]["signal_reason"]


def test_zero_quantity_reason_explains_cash(tmp_path, monkeypatch) -> None:
    paths = _setup(tmp_path, monkeypatch)
    save_live_config(
        paths.config_path,
        LiveConfig(
            mode=TradingMode.live,
            symbols=["AAA"],
            total_cash=500.0,
            assets=[SymbolParams("AAA", buy_rise_pct=1.0, sell_drop_pct=50.0)],
            allow_fractional_default=False,
        ),
    )
    picker = PickerPaths(project_root=tmp_path)
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="t",
            run_id="r",
            symbols=[ActiveSymbol("AAA", 0.01, 0.5, awaiting_first_buy=False)],
        ),
    )
    # Seed trough so BUY fires; cash too small for 1 whole share at ~$800.
    paths.state_path.write_text(
        '{"assets":{"AAA":{"cash":500.0,"shares":0.0,"peak":null,"trough":700.0}},'
        '"cash_usd":500.0,"orders_today":0,"reject_streak":0}',
        encoding="utf-8",
    )
    broker = InMemoryBroker(500.0, last_prices={"AAA": 800.0})
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    history = [700.0] * 20 + [800.0]
    out = run_live_once(
        paths,
        broker,
        risk,
        audit,
        t1,
        {"AAA": 800.0},
        {"AAA": "b1"},
        closes_by_symbol={"AAA": history},
    )
    d0 = out["decisions"][0]
    assert d0["signal"] == "BUY"
    assert d0["plan"] == "can't afford 1 share"
    assert "can't buy 1 share" in d0["signal_reason"]
    assert "$800.00" in d0["signal_reason"]


def test_latest_prices_forwards_close_series() -> None:
    from app.live_worker import _latest_prices

    class _Broker:
        def latest_hourly_closes(self, symbols, *, use_rth=True):
            assert symbols == ["AAA"]
            assert use_rth is True
            return (
                {"AAA": 101.5},
                {"AAA": "2026-10-07T19:00:00+00:00"},
                {"AAA": [100.0] * 19 + [101.5]},
            )

    prices, bars, closes, source = _latest_prices(["AAA"], broker_inner=_Broker())
    assert source == "ibkr_rth_hourly"
    assert prices["AAA"] == 101.5
    assert bars["AAA"].startswith("2026-10-07")
    assert len(closes["AAA"]) == 20
    assert closes["AAA"][-1] == 101.5
