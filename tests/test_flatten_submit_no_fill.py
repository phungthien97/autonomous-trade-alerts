"""Hard-rotate must not treat unfilled SELL submits as done.

Nov 3: NCLH SELL returned submitted, idempotency marked done, exit_pending
zeroed local shares — while broker stayed long. Flatten never completed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.audit.log import AuditLog
from app.broker.base import OrderResult
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.executor import execute_intent
from app.live.idempotency import IdempotencyStore, intent_key
from app.live.modes import TradingMode
from app.live.planner import OrderIntent
from app.live.queue import PendingIntentStore
from app.live_worker import run_live_once
from app.paths import LivePaths, PickerPaths
from app.picker.active import (
    ROTATION_FLATTENING,
    ActiveSelection,
    ActiveSymbol,
    load_active,
    save_active,
)
from app.risk import RiskController


class _SubmitNoFillBroker:
    """Mimics IBKR returning Submitted without ever reducing the long."""

    def __init__(self, positions: dict[str, float], prices: dict[str, float]) -> None:
        self.positions = dict(positions)
        self.last_prices = dict(prices)
        self.cash = 100_000.0
        self.orders: list[tuple[str, str, float]] = []

    def get_positions(self) -> dict[str, float]:
        return dict(self.positions)

    def get_account_snapshot(self):
        from app.account_snapshot import AccountSnapshot

        invested = sum(
            float(self.positions.get(s, 0)) * float(self.last_prices.get(s, 0))
            for s in self.positions
        )
        return AccountSnapshot(
            cash_usd=self.cash,
            available_funds_usd=self.cash + invested,
            buying_power_usd=self.cash * 2,
            equity_usd=self.cash + invested,
            account_currency="USD",
            gross_position_value_usd=invested,
        )

    def supports_fractional(self, symbol: str) -> bool:
        return True

    def cancel_order(self, order_id: str) -> None:
        return None

    def place_market_order(self, symbol: str, side: str, quantity: float, dry_run=None):
        self.orders.append((symbol, side, float(quantity)))
        # Ghost submit — position unchanged (disconnect-cancel race).
        return OrderResult("ghost-1", "cancelled", 0.0, 0.0, float(quantity))


def test_executor_does_not_mark_idempotency_on_cancelled_sell(tmp_path) -> None:
    broker = _SubmitNoFillBroker({"NCLH": 100.0}, {"NCLH": 18.0})
    idem = IdempotencyStore(tmp_path / "id.json")
    key = intent_key("NCLH", "bar-1", "SELL")
    result = execute_intent(
        OrderIntent("NCLH", "SELL", 100.0, 1.0, "bar-1", "flatten"),
        broker,
        idem,
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.broker_paper,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert result.status == "cancelled"
    assert idem.already_done(key) is False
    # Same bar must be allowed to retry.
    second = execute_intent(
        OrderIntent("NCLH", "SELL", 100.0, 1.0, "bar-1", "flatten"),
        broker,
        idem,
        AuditLog(tmp_path / "a2.jsonl"),
        TradingMode.broker_paper,
        True,
        PendingIntentStore(tmp_path / "q2.json"),
    )
    assert second.status == "cancelled"
    assert len(broker.orders) == 2


def test_hard_rotate_cancelled_sell_keeps_flattening_and_broker_shares(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "YES")
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(
            mode=TradingMode.broker_paper,
            symbols=["NCLH", "MRNA"],
            total_cash=100_000.0,
            trading_budget_usd=100_000.0,
            assets=[
                SymbolParams("NCLH", buy_rise_pct=1.0, sell_drop_pct=5.0),
                SymbolParams("MRNA", buy_rise_pct=1.0, sell_drop_pct=5.0),
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
                ActiveSymbol("NCLH", 0.01, 0.05, awaiting_first_buy=True),
                ActiveSymbol("MRNA", 0.01, 0.05, awaiting_first_buy=True),
            ],
        ),
    )
    paths.state_path.write_text(
        json.dumps(
            {
                "cash_usd": 50_000.0,
                "assets": {
                    "NCLH": {
                        "cash": 0.0,
                        "shares": 100.0,
                        "peak": 18.0,
                        "trough": 17.0,
                        "last_price": 18.0,
                        "exit_pending": False,
                    },
                    "MRNA": {
                        "cash": 50_000.0,
                        "shares": 0.0,
                        "peak": None,
                        "trough": None,
                        "last_price": 200.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    broker = _SubmitNoFillBroker(
        {"NCLH": 100.0},
        {"NCLH": 18.0, "MRNA": 200.0},
    )
    out = run_live_once(
        paths,
        broker,
        RiskController(paths.risk_path),
        AuditLog(paths.audit_log_path),
        datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc),
        {"NCLH": 18.0, "MRNA": 200.0},
        {"NCLH": "2026-11-03T15:00:00+00:00", "MRNA": "2026-11-03T15:00:00+00:00"},
        closes_by_symbol={"NCLH": [17.0] * 20, "MRNA": [190.0] * 20},
    )
    nclh = next(d for d in out["decisions"] if d["symbol"] == "NCLH")
    assert nclh["signal"] == "SELL"
    # Must not pretend we are flat locally.
    state = json.loads(paths.state_path.read_text(encoding="utf-8"))
    assert float(state["assets"]["NCLH"]["shares"]) == 100.0
    assert state["assets"]["NCLH"].get("exit_pending") is not True
    active = load_active(picker.active_selection_path)
    assert active is not None
    assert active.rotation_phase == ROTATION_FLATTENING
    assert float(broker.get_positions().get("NCLH", 0)) == 100.0
