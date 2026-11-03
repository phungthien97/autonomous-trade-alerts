"""Hard rotate: flatten entire book, then allow new-slate buys."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.audit.log import AuditLog
from app.broker import InMemoryBroker
from app.live.config import LiveConfig, SymbolParams, load_live_config, save_live_config
from app.live.modes import TradingMode
from app.live_worker import run_live_once
from app.paths import LivePaths, PickerPaths
from app.picker.active import (
    ROTATION_FLATTENING,
    ROTATION_IDLE,
    ActiveSelection,
    ActiveSymbol,
    load_active,
    save_active,
)
from app.risk import RiskController


def test_hard_rotate_flattens_then_idles(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "YES")
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(
            mode=TradingMode.live,
            symbols=["OLD", "NEW"],
            total_cash=10_000.0,
            trading_budget_usd=10_000.0,
            assets=[
                SymbolParams("OLD", buy_rise_pct=1.0, sell_drop_pct=50.0),
                SymbolParams("NEW", buy_rise_pct=1.0, sell_drop_pct=50.0),
            ],
            allow_fractional_default=True,
            use_account_cash=True,
        ),
    )
    picker = PickerPaths(project_root=tmp_path)
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="t",
            run_id="r",
            rotation_phase=ROTATION_FLATTENING,
            symbols=[
                ActiveSymbol("NEW", 0.01, 0.5, awaiting_first_buy=True),
                ActiveSymbol("OLD", 0.01, 0.5, exit_only=True),
            ],
        ),
    )
    paths.state_path.write_text(
        json.dumps(
            {
                "cash_usd": 0.0,
                "assets": {
                    "OLD": {
                        "cash": 0.0,
                        "shares": 10.0,
                        "peak": 100.0,
                        "trough": 90.0,
                        "last_price": 100.0,
                    },
                    "NEW": {
                        "cash": 0.0,
                        "shares": 0.0,
                        "peak": None,
                        "trough": None,
                        "last_price": 50.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    broker = InMemoryBroker(10_000.0, last_prices={"OLD": 100.0, "NEW": 50.0})
    broker.positions["OLD"] = 10.0
    risk = RiskController(paths.risk_path)
    audit = AuditLog(paths.audit_log_path)
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)

    out = run_live_once(
        paths,
        broker,
        risk,
        audit,
        t1,
        {"OLD": 100.0, "NEW": 50.0},
        {"OLD": "b1", "NEW": "b2"},
        closes_by_symbol={"NEW": [40.0] * 20},
    )
    old_dec = next(d for d in out["decisions"] if d["symbol"] == "OLD")
    new_dec = next(d for d in out["decisions"] if d["symbol"] == "NEW")
    assert old_dec["signal"] == "SELL"
    assert "Hard rotate" in (old_dec["signal_reason"] or "")
    assert new_dec["signal"] is None
    assert new_dec.get("gate") in {None, "hard_rotate_flattening"} or "flat" in (
        new_dec.get("signal_reason") or ""
    ).lower()
    assert float(broker.get_positions().get("OLD", 0) or 0) == 0.0

    active = load_active(picker.active_selection_path)
    assert active is not None
    assert active.rotation_phase == ROTATION_IDLE
    assert active.get("OLD") is None  # pruned after flatten
    cfg = load_live_config(paths.config_path)
    assert "OLD" not in [str(s).upper() for s in cfg.symbols]
    assert "NEW" in [str(s).upper() for s in cfg.symbols]
