"""All-in / all-out share quantities."""

from __future__ import annotations

import math


def buy_share_quantity(cash: float, price: float, allow_fractional: bool) -> float:
    if price <= 0:
        raise ValueError("price must be positive")
    if cash <= 0:
        return 0.0
    if allow_fractional:
        qty = cash / price
        if not math.isfinite(qty):
            raise ValueError("quantity is not finite")
        return qty
    qty = math.floor(cash / price)
    if qty < 1:
        return 0.0
    return float(qty)


def sell_share_quantity(shares_held: float, allow_fractional: bool) -> float:
    if shares_held <= 0:
        return 0.0
    if allow_fractional:
        return float(shares_held)
    whole = math.floor(shares_held + 1e-9)
    return float(whole)


def residual_cash_after_buy(cash: float, price: float, qty: float) -> float:
    return float(cash) - float(qty) * float(price)
