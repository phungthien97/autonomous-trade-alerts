import pytest

from app.live import (
    AccountSnapshot,
    assert_never_borrow,
    assert_never_short,
    sell_qty_would_short,
    would_create_debit,
)


def _snap(
    cash: float,
    *,
    available: float | None = None,
    buying_power: float | None = None,
    gross: float | None = 0.0,
) -> AccountSnapshot:
    return AccountSnapshot(
        cash_usd=cash,
        buying_power_usd=buying_power if buying_power is not None else cash * 2,
        equity_usd=cash + (gross or 0.0),
        available_funds_usd=available if available is not None else cash,
        gross_position_value_usd=gross,
    )


def test_affordable_buy() -> None:
    snap = _snap(1000.0)
    assert would_create_debit("BUY", 900.0, 5.0, snap) is False
    assert_never_borrow("BUY", 900.0, 5.0, snap)


def test_oversize_buy_rejected() -> None:
    snap = _snap(100.0)
    assert would_create_debit("BUY", 100.0, 1.0, snap) is True
    with pytest.raises(ValueError, match="spendable|exceed"):
        assert_never_borrow("BUY", 100.0, 1.0, snap)


def test_sell_does_not_create_debit() -> None:
    snap = _snap(0.0)
    assert would_create_debit("SELL", 500.0, 1.0, snap) is False


def test_available_funds_allows_same_day_turnover_not_leverage() -> None:
    """R4: when flat, size on AvailableFunds; ignore inflated BuyingPower."""
    # Unsettled sell credit while flat: cash low, available higher; BP is 3x leverage bait
    snap = _snap(100.0, available=500.0, buying_power=1500.0, gross=0.0)
    assert snap.spendable_usd == 500.0
    assert would_create_debit("BUY", 480.0, 1.0, snap) is False
    assert would_create_debit("BUY", 500.0, 1.0, snap) is True
    # Must not treat BuyingPower 1500 as spendable
    assert would_create_debit("BUY", 1400.0, 1.0, snap) is True


def test_long_positions_cap_spendable_at_cash() -> None:
    """While long, AvailableFunds > cash is margin against stock — never-borrow."""
    snap = _snap(313_012.93, available=757_902.61, buying_power=2_500_000.0, gross=663_699.32)
    assert snap.spendable_usd == pytest.approx(313_012.93)
    assert would_create_debit("BUY", 313_000.0, 10.0, snap) is False
    assert would_create_debit("BUY", 400_000.0, 10.0, snap) is True
    with pytest.raises(ValueError, match="spendable|exceed"):
        assert_never_borrow("BUY", 400_000.0, 10.0, snap)


def test_never_short_guard() -> None:
    assert sell_qty_would_short(504.0, 504.0) is False
    assert sell_qty_would_short(505.0, 504.0) is True
    assert sell_qty_would_short(1.0, 0.0) is True
    assert_never_short(100.0, 100.0)
    with pytest.raises(ValueError, match="short"):
        assert_never_short(101.0, 100.0)
