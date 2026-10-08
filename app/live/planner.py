from __future__ import annotations

from dataclasses import dataclass

from app.fees import estimate_equity_order_fees
from app.fees.model import FeeSchedule
from app.account_snapshot import AccountSnapshot
from app.live.risk_limits import would_create_debit
from app.live.sizing import buy_share_quantity, sell_share_quantity
from app.strategy import StrategyState


@dataclass
class OrderIntent:
    symbol: str
    side: str
    quantity: float
    estimated_fees: float
    bar_ts: str
    reason: str
    limit_price: float | None = None


def plan_from_signal(
    symbol: str,
    signal: str | None,
    strategy_state: StrategyState,
    price: float,
    allow_fractional: bool,
    account_snapshot: AccountSnapshot,
    fee_schedule: FeeSchedule,
    bar_ts: str,
) -> tuple[OrderIntent | None, str]:
    if signal not in ("BUY", "SELL"):
        return None, "no signal"
    if signal == "BUY":
        budget = min(strategy_state.cash, account_snapshot.spendable_usd)
        qty = buy_share_quantity(budget, price, allow_fractional)
        if qty <= 0:
            return None, "zero quantity"
        fees = estimate_equity_order_fees("BUY", qty, price, fee_schedule)["total"]
        if would_create_debit("BUY", qty * price, fees, account_snapshot):
            spendable = account_snapshot.spendable_usd - fees
            qty = buy_share_quantity(spendable, price, allow_fractional)
            if qty <= 0:
                return None, "would borrow"
            fees = estimate_equity_order_fees("BUY", qty, price, fee_schedule)["total"]
            if would_create_debit("BUY", qty * price, fees, account_snapshot):
                return None, "would borrow"
        return (
            OrderIntent(symbol, "BUY", qty, fees, bar_ts, "buy signal"),
            "planned",
        )
    qty = sell_share_quantity(strategy_state.shares, allow_fractional)
    if qty <= 0:
        return None, "zero quantity"
    fees = estimate_equity_order_fees("SELL", qty, price, fee_schedule)["total"]
    return OrderIntent(symbol, "SELL", qty, fees, bar_ts, "sell signal"), "planned"
