"""Submit guard around a broker client.

broker_paper may submit (default paper port 4002).
live submits only when LIVE_TRADING_CONFIRM=YES (typical live port 4001).
live_dry_run and sim never call place_market_order.
"""

from __future__ import annotations

import os

from app.broker.base import OrderResult
from app.live.modes import TradingMode


class BrokerGateway:
    def __init__(self, inner, mode: TradingMode) -> None:
        self.inner = inner
        self.mode = mode
        self.submit_count = 0

    def get_account_snapshot(self):
        return self.inner.get_account_snapshot()

    def get_positions(self):
        return self.inner.get_positions()

    def supports_fractional(self, symbol: str) -> bool:
        return self.inner.supports_fractional(symbol)

    def cancel_order(self, order_id: str) -> None:
        self.inner.cancel_order(order_id)

    def place_market_order(self, symbol: str, side: str, quantity: float, dry_run: bool | None = None) -> OrderResult:
        if self.mode in (TradingMode.sim, TradingMode.live_dry_run) or dry_run:
            return OrderResult("blocked", "dry_run", 0.0, 0.0, float(quantity))
        if self.mode is TradingMode.live and os.environ.get("LIVE_TRADING_CONFIRM") != "YES":
            return OrderResult("blocked", "rejected", 0.0, 0.0, float(quantity))
        if self.mode not in (TradingMode.broker_paper, TradingMode.live):
            return OrderResult("blocked", "rejected", 0.0, 0.0, float(quantity))
        self.submit_count += 1
        return self.inner.place_market_order(symbol, side, quantity)
