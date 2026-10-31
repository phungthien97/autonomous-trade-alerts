"""Equal-among-flats budgets, mid-cycle reserve, FX, and 1-share stretch."""

from __future__ import annotations

import pytest

from app.account_snapshot import AccountSnapshot
from app.fees import default_ibkr_us_stock_schedule
from app.live.planner import plan_from_signal
from app.picker.sizing import resolve_equal_buy_cash_cap, sleeve_buy_budget
from app.strategy import StrategyState


def test_mid_cycle_reserve_keeps_equal_budgets() -> None:
    """After a BUY reserves a flat slot and cash drops, next equal cap stays ~equal."""
    n_active = 5
    pool = 500.0
    first = sleeve_buy_budget(pool, n_active, n_already_long=0)
    assert first == pytest.approx(100.0)
    # First fill spends its cap; n_long reserved; spendable refreshes.
    pool_after = pool - first
    second = sleeve_buy_budget(pool_after, n_active, n_already_long=1)
    assert second == pytest.approx(100.0)
    # Bug regression: forgetting to reserve n_long undersizes later sleeves.
    buggy = sleeve_buy_budget(pool_after, n_active, n_already_long=0)
    assert buggy == pytest.approx(80.0)
    assert second > buggy


def test_inflight_notional_prevents_oversubscribe_when_cash_stale() -> None:
    """Submitted-not-filled: subtract inflight so equal caps cannot sum above pool."""
    n_active = 5
    pool = 50_000.0
    inflight = 0.0
    caps: list[float] = []
    for i in range(5):
        available = max(0.0, pool - inflight)
        cap = sleeve_buy_budget(available, n_active, n_already_long=i)
        caps.append(cap)
        inflight += cap
    assert sum(caps) == pytest.approx(50_000.0)
    # Without inflight haircut, shrinking denominator oversubscribes.
    buggy_total = 0.0
    for i in range(5):
        buggy_total += sleeve_buy_budget(pool, n_active, n_already_long=i)
    assert buggy_total > 50_000.0


def test_cad_spendable_usd_feeds_equal_budget() -> None:
    snap = AccountSnapshot(
        cash_usd=1400.0,
        buying_power_usd=1400.0,
        equity_usd=1400.0,
        available_funds_usd=1400.0,
        gross_position_value_usd=0.0,
        account_currency="CAD",
        fx_rates={"USD": 1.4, "CAD": 1.0, "BASE": 1.0},
        usd_cad_rate=1.4,
    )
    assert snap.spendable_native == pytest.approx(1400.0)
    assert snap.spendable_usd == pytest.approx(1000.0)
    # Five flat sleeves → $200 USD each, not $280 CAD-as-USD.
    assert sleeve_buy_budget(snap.spendable_usd, 5, 0) == pytest.approx(200.0)


def test_stretch_when_equal_slot_below_one_share() -> None:
    # Equal slot $600, share $800, pool still has room → stretch to 1 share.
    cap = resolve_equal_buy_cash_cap(
        3000.0,
        n_active_non_exit_only=5,
        n_already_long=0,
        price=800.0,
        allow_fractional=False,
    )
    assert cap == pytest.approx(800.0)


def test_no_stretch_when_share_exceeds_entire_pool() -> None:
    cap = resolve_equal_buy_cash_cap(
        500.0,
        n_active_non_exit_only=5,
        n_already_long=0,
        price=800.0,
        allow_fractional=False,
    )
    # Equal slot is $100; stretch refused — planner will zero-qty.
    assert cap == pytest.approx(100.0)
    state = StrategyState(cash=500.0, shares=0.0, peak=None, trough=90.0)
    snap = AccountSnapshot(500.0, 500.0, 500.0, available_funds_usd=500.0)
    intent, reason = plan_from_signal(
        "FICO",
        "BUY",
        state,
        800.0,
        False,
        snap,
        default_ibkr_us_stock_schedule(),
        "bar-stretch",
        buy_cash_cap=cap,
    )
    assert intent is None
    assert reason == "zero quantity"


def test_stretch_plans_one_whole_share() -> None:
    pool = 3000.0
    price = 800.0
    cap = resolve_equal_buy_cash_cap(
        pool,
        n_active_non_exit_only=5,
        n_already_long=0,
        price=price,
        allow_fractional=False,
    )
    state = StrategyState(cash=0.0, shares=0.0, peak=None, trough=700.0)
    snap = AccountSnapshot(pool, pool, pool, available_funds_usd=pool)
    intent, reason = plan_from_signal(
        "FICO",
        "BUY",
        state,
        price,
        False,
        snap,
        default_ibkr_us_stock_schedule(),
        "bar-ok",
        buy_cash_cap=cap,
    )
    assert reason == "planned"
    assert intent is not None
    assert intent.quantity == 1.0


def test_equal_cap_unchanged_when_affordable() -> None:
    cap = resolve_equal_buy_cash_cap(
        1000.0,
        n_active_non_exit_only=5,
        n_already_long=0,
        price=100.0,
        allow_fractional=False,
    )
    assert cap == pytest.approx(200.0)
