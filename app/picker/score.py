"""After-fee peak/trough score vs buy-and-hold on a close series.

Fee convention
--------------
On each strategy BUY: estimate fees for the intended share quantity at the fill
price, then spend ``cash - fee`` on shares (all-in sleeve). If cash cannot cover
fees, skip the buy and keep cash.

On each strategy SELL: convert shares to cash at the fill price, then subtract
the sell-side fee from proceeds (cash floored at 0).

Buy-and-hold: pay a single BUY fee at the first close, then mark to market at
the last close (no terminal sell fee). Edge compares after-fee strategy return
to that B&H return.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.fees.model import FeeSchedule, default_ibkr_us_stock_schedule, estimate_equity_order_fees
from app.strategy import StrategyState, portfolio_value, step_signal


@dataclass(frozen=True)
class SymbolScore:
    strategy_final_value: float
    bh_final_value: float
    strategy_return: float
    bh_return: float
    edge: float
    round_trips: int


def _apply_buy_with_fees(state: StrategyState, price: float, schedule: FeeSchedule) -> None:
    cash = float(state.cash)
    if cash <= 0 or price <= 0:
        return
    qty_guess = cash / price
    fee = estimate_equity_order_fees("BUY", qty_guess, price, schedule)["total"]
    spendable = cash - fee
    if spendable <= 0:
        return
    state.shares = spendable / price
    state.cash = 0.0
    state.peak = price
    state.trough = None


def _apply_sell_with_fees(state: StrategyState, price: float, schedule: FeeSchedule) -> None:
    qty = float(state.shares)
    if qty <= 0:
        return
    fee = estimate_equity_order_fees("SELL", qty, price, schedule)["total"]
    proceeds = qty * price - fee
    state.cash = max(0.0, proceeds)
    state.shares = 0.0
    state.trough = price
    state.peak = None


def score_symbol_series(
    closes: Sequence[float],
    buy_rise: float,
    sell_drop: float,
    initial_cash: float = 1000.0,
    schedule: FeeSchedule | None = None,
) -> SymbolScore:
    """Run fee-aware peak/trough vs B&H on ``closes``; return edge metrics."""
    sched = schedule if schedule is not None else default_ibkr_us_stock_schedule()
    prices = [float(p) for p in closes]
    if not prices:
        return SymbolScore(
            strategy_final_value=float(initial_cash),
            bh_final_value=float(initial_cash),
            strategy_return=0.0,
            bh_return=0.0,
            edge=0.0,
            round_trips=0,
        )

    # --- buy and hold (entry fee only, MTM at end) ---
    first = prices[0]
    bh_qty_guess = float(initial_cash) / first if first > 0 else 0.0
    bh_fee = estimate_equity_order_fees("BUY", bh_qty_guess, first, sched)["total"]
    bh_spendable = max(0.0, float(initial_cash) - bh_fee)
    bh_shares = bh_spendable / first if first > 0 else 0.0
    bh_final = bh_shares * prices[-1]

    # --- strategy ---
    # Start in cash so the first entry must clear buy_rise from the trough
    # (matches live/paper cash sleeves; not the invested-at-bar0 paper helper).
    state = StrategyState(cash=float(initial_cash), shares=0.0, peak=None, trough=float(first))
    probe = StrategyState(cash=float(initial_cash), shares=0.0, peak=None, trough=float(first))
    round_trips = 0

    for price in prices[1:]:
        # Probe signal on a fee-unaware copy of trough/peak/position shape.
        probe.cash = state.cash
        probe.shares = state.shares
        probe.peak = state.peak
        probe.trough = state.trough
        action, _ = step_signal(probe, price, buy_rise=buy_rise, sell_drop=sell_drop)
        if action == "BUY":
            # Restore pre-probe position; apply fee-aware fill.
            _apply_buy_with_fees(state, price, sched)
        elif action == "SELL":
            _apply_sell_with_fees(state, price, sched)
            round_trips += 1
        else:
            # Keep trough/peak tracking in sync with probe when no trade.
            state.peak = probe.peak
            state.trough = probe.trough

    strategy_final = portfolio_value(state, prices[-1])
    strategy_return = strategy_final / float(initial_cash) - 1.0
    bh_return = bh_final / float(initial_cash) - 1.0
    return SymbolScore(
        strategy_final_value=strategy_final,
        bh_final_value=bh_final,
        strategy_return=strategy_return,
        bh_return=bh_return,
        edge=strategy_return - bh_return,
        round_trips=round_trips,
    )
