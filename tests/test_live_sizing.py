import math

import pytest

from app.live import buy_share_quantity, residual_cash_after_buy, sell_share_quantity


def test_fractional_buy() -> None:
    qty = buy_share_quantity(333.0, 250.0, allow_fractional=True)
    assert math.isclose(qty, 333.0 / 250.0)


def test_whole_share_leaves_residual_cash() -> None:
    qty = buy_share_quantity(1000.0, 333.0, allow_fractional=False)
    assert qty == 3.0
    leftover = residual_cash_after_buy(1000.0, 333.0, qty)
    assert leftover == pytest.approx(1.0)


def test_zero_cash_and_cannot_afford_one_share() -> None:
    assert buy_share_quantity(0.0, 100.0, True) == 0.0
    assert buy_share_quantity(50.0, 100.0, False) == 0.0


def test_invalid_price_raises() -> None:
    with pytest.raises(ValueError):
        buy_share_quantity(100.0, 0.0, True)


def test_sell_fractional_and_whole() -> None:
    assert sell_share_quantity(1.25, True) == pytest.approx(1.25)
    assert sell_share_quantity(3.0, False) == 3.0
    assert sell_share_quantity(3.8, False) == 3.0
