from __future__ import annotations

from app.broker.base import OrderResult
from app.account_snapshot import AccountSnapshot


class InMemoryBroker:
    def __init__(
        self,
        cash_usd: float,
        positions: dict[str, float] | None = None,
        last_prices: dict[str, float] | None = None,
        fractional: bool = True,
        partial_fill_ratio: float | None = None,
    ) -> None:
        self.cash_usd = float(cash_usd)
        self.positions = dict(positions or {})
        self.last_prices = dict(last_prices or {})
        self.fractional = fractional
        self.partial_fill_ratio = partial_fill_ratio
        self.cancelled: list[str] = []
        self.orders: list[OrderResult] = []
        self._seq = 0

    def get_account_snapshot(self) -> AccountSnapshot:
        stock_value = 0.0
        for symbol, shares in self.positions.items():
            stock_value += float(shares) * float(self.last_prices.get(symbol, 0.0))
        equity = self.cash_usd + stock_value
        return AccountSnapshot(
            cash_usd=self.cash_usd,
            buying_power_usd=self.cash_usd,
            equity_usd=equity,
            available_funds_usd=self.cash_usd,
            gross_position_value_usd=stock_value,
            accrued_cash_usd=0.0,
        )

    def get_positions(self) -> dict[str, float]:
        return dict(self.positions)

    def supports_fractional(self, symbol: str) -> bool:
        return self.fractional

    def place_market_order(self, symbol: str, side: str, quantity: float) -> OrderResult:
        price = float(self.last_prices[symbol])
        qty = float(quantity)
        self._seq += 1
        order_id = f"mem-{self._seq}"
        if self.partial_fill_ratio is not None and 0 < self.partial_fill_ratio < 1 and qty > 0:
            filled = qty * self.partial_fill_ratio
            remaining = qty - filled
            if self._apply_fill(symbol, side, filled, price) is None:
                result = OrderResult(order_id, "rejected", 0.0, price, qty)
                self.orders.append(result)
                return result
            result = OrderResult(order_id, "partial", filled, price, remaining)
            self.orders.append(result)
            return result
        if qty <= 0 or price <= 0:
            result = OrderResult(order_id, "rejected", 0.0, price)
            self.orders.append(result)
            return result
        applied = self._apply_fill(symbol, side, qty, price)
        if applied is None:
            result = OrderResult(order_id, "rejected", 0.0, price)
            self.orders.append(result)
            return result
        result = OrderResult(order_id, "filled", qty, price)
        self.orders.append(result)
        return result

    def _apply_fill(self, symbol: str, side: str, qty: float, price: float) -> bool | None:
        if side == "BUY":
            cost = qty * price
            if cost > self.cash_usd + 1e-9:
                return None
            self.cash_usd -= cost
            self.positions[symbol] = self.positions.get(symbol, 0.0) + qty
            return True
        if side == "SELL":
            held = self.positions.get(symbol, 0.0)
            if qty > held + 1e-9:
                return None
            self.positions[symbol] = held - qty
            self.cash_usd += qty * price
            return True
        return None

    def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)
