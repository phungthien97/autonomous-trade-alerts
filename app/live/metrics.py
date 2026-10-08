"""After-fee live portfolio vs equal-weight buy-and-hold."""

from __future__ import annotations

from app.fees import default_ibkr_us_stock_schedule, estimate_equity_order_fees
from app.fees.model import FeeSchedule


def returns_from_values(starting_cash_total: float, bot_end: float, bh_end: float) -> dict[str, float]:
    if starting_cash_total <= 0:
        raise ValueError("starting_cash_total must be positive")
    bot_return_pct = (bot_end / starting_cash_total - 1.0) * 100.0
    bh_return_pct = (bh_end / starting_cash_total - 1.0) * 100.0
    return {
        "bot_return_pct": bot_return_pct,
        "bh_return_pct": bh_return_pct,
        "edge_pct": bot_return_pct - bh_return_pct,
    }


def equal_weight_bh_value(
    starting_cash_total: float,
    symbols: list[str],
    start_prices: dict[str, float],
    end_prices: dict[str, float],
    schedule: FeeSchedule | None = None,
    subtract_initial_buy_fees: bool = True,
) -> float:
    if not symbols:
        raise ValueError("symbols required")
    fee_schedule = schedule or default_ibkr_us_stock_schedule()
    sleeve = starting_cash_total / len(symbols)
    value = 0.0
    for symbol in symbols:
        start_px = float(start_prices[symbol])
        end_px = float(end_prices[symbol])
        if start_px <= 0:
            raise ValueError(f"bad start price for {symbol}")
        shares = sleeve / start_px
        value += shares * end_px
        if subtract_initial_buy_fees:
            fees = estimate_equity_order_fees("BUY", shares, start_px, fee_schedule)
            value -= fees["total"]
    return value
