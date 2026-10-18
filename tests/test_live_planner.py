from app.fees import default_ibkr_us_stock_schedule
from app.live import AccountSnapshot, plan_from_signal
from app.live.sizing import buy_share_quantity
from app.strategy import StrategyState


def test_buy_intent_quantity() -> None:
    state = StrategyState(cash=1000.0, shares=0.0, peak=None, trough=90.0)
    snap = AccountSnapshot(1100.0, 1100.0, 1100.0)
    intent, reason = plan_from_signal(
        "AAPL", "BUY", state, 100.0, True, snap, default_ibkr_us_stock_schedule(), "bar-1"
    )
    assert reason == "planned"
    assert intent is not None
    assert intent.quantity == buy_share_quantity(1000.0, 100.0, True)
    assert intent.side == "BUY"


def test_unaffordable_buy_rejected() -> None:
    # Whole shares: $50 cannot buy 1 share at $100 (IBKR API path).
    state = StrategyState(cash=1000.0, shares=0.0, peak=None, trough=90.0)
    snap = AccountSnapshot(50.0, 50.0, 50.0, available_funds_usd=50.0)
    intent, reason = plan_from_signal(
        "AAPL", "BUY", state, 100.0, False, snap, default_ibkr_us_stock_schedule(), "bar-1"
    )
    assert intent is None
    assert reason == "zero quantity"


def test_sell_all_shares() -> None:
    state = StrategyState(cash=0.0, shares=3.5, peak=110.0, trough=None)
    snap = AccountSnapshot(0.0, 0.0, 350.0)
    intent, reason = plan_from_signal(
        "AAPL", "SELL", state, 100.0, True, snap, default_ibkr_us_stock_schedule(), "bar-2"
    )
    assert reason == "planned"
    assert intent is not None
    assert intent.quantity == 3.5


def test_hold_returns_none() -> None:
    state = StrategyState(cash=100.0, shares=0.0, peak=None, trough=100.0)
    snap = AccountSnapshot(100.0, 100.0, 100.0)
    intent, reason = plan_from_signal(
        "AAPL", None, state, 100.0, True, snap, default_ibkr_us_stock_schedule(), "bar-3"
    )
    assert intent is None
    assert reason == "no signal"


def test_buy_cash_cap_overrides_stale_sleeve_cash() -> None:
    # Sleeve cash too small for 1 share; equal-weight cap from spendable is enough.
    state = StrategyState(cash=333.0, shares=0.0, peak=None, trough=90.0)
    snap = AccountSnapshot(3000.0, 3000.0, 3000.0, available_funds_usd=3000.0)
    intent, reason = plan_from_signal(
        "AAPL",
        "BUY",
        state,
        350.0,
        False,
        snap,
        default_ibkr_us_stock_schedule(),
        "bar-4",
        buy_cash_cap=1000.0,
    )
    assert reason == "planned"
    assert intent is not None
    assert intent.quantity == 2.0
