"""Fast picker E2E: rank → apply → live SMA gate blocks buy."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.audit.log import AuditLog
from app.broker import InMemoryBroker
from app.live.config import load_live_config
from app.live.modes import TradingMode
from app.live.config import LiveConfig, save_live_config
from app.live_worker import run_live_once
from app.paths import LivePaths, PickerPaths, StatePaths
from app.picker.active import load_active
from app.picker.apply import apply_pending_selection
from app.picker.bars import FixtureBarProvider
from app.picker.run import run_ranking
from app.risk import RiskController

ET = ZoneInfo("America/New_York")


def _series(start: date, days: int, base: float = 100.0):
    rows = []
    px = base
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        if i < days // 2:
            px *= 0.985
        else:
            px *= 1.015
        rows.append((datetime(d.year, d.month, d.day, 10, 30, tzinfo=ET), px))
    return rows


def test_picker_e2e_rank_apply_live_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "YES")
    picker = PickerPaths(project_root=tmp_path)
    live = LivePaths(project_root=tmp_path)
    v1 = StatePaths(version="v1", project_root=tmp_path)
    v2 = StatePaths(version="v2", project_root=tmp_path)

    save_live_config(
        live.config_path,
        LiveConfig(mode=TradingMode.live, symbols=["OLD"], total_cash=1000.0),
    )
    for paths in (v1, v2):
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            '{"initial_cash": 1000.0, "assets": []}', encoding="utf-8"
        )
        paths.state_path.write_text('{"assets": {}}', encoding="utf-8")

    start = date(2026, 9, 1)
    provider = FixtureBarProvider(
        series={
            "NEWA": _series(start, 50, 100.0),
            "NEWB": _series(start, 50, 80.0),
        }
    )
    ranked = run_ranking(
        as_of=date(2026, 10, 11),
        sp500_loader=lambda: ["NEWA", "NEWB"],
        bar_provider=provider,
        picker_paths=picker,
        active_symbols=["OLD"],
        send_email=False,
        dry_run=False,
    )
    assert ranked.ok and ranked.pending_written

    applied = apply_pending_selection(
        picker,
        live,
        v1,
        v2,
        now=datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc),
    )
    assert applied.applied is True
    cfg = load_live_config(live.config_path)
    assert "NEWA" in cfg.symbols or "NEWB" in cfg.symbols
    active = load_active(picker.active_selection_path)
    assert active is not None
    added = [s for s in active.symbols if s.awaiting_first_buy]
    assert added

    # Live gate: below-SMA history blocks first buy for an awaiting symbol.
    symbol = added[0].symbol
    history = [110.0] * 20
    broker = InMemoryBroker(1000.0, last_prices={symbol: 100.0})
    # Ensure config still has the symbol with tight buy threshold for signal
    save_live_config(
        live.config_path,
        LiveConfig(
            mode=TradingMode.live,
            symbols=[symbol],
            total_cash=1000.0,
            assets=[a for a in cfg.assets if a.symbol == symbol]
            or cfg.assets[:1],
        ),
    )
    # Force buy_rise small via rewriting asset pcts
    cfg2 = load_live_config(live.config_path)
    cfg2.assets[0].buy_rise_pct = 1.0
    cfg2.assets[0].sell_drop_pct = 50.0
    save_live_config(live.config_path, cfg2)

    risk = RiskController(live.risk_path)
    audit = AuditLog(live.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    run_live_once(live, broker, risk, audit, t1, {symbol: 100.0}, {symbol: "b1"}, closes_by_symbol={symbol: history})
    out = run_live_once(
        live,
        broker,
        risk,
        audit,
        t2,
        {symbol: 101.5},
        {symbol: "b2"},
        closes_by_symbol={symbol: history + [101.5]},
    )
    assert broker.get_positions().get(symbol, 0) == 0
    assert out["decisions"][0].get("gate") == "sma20_gate"
