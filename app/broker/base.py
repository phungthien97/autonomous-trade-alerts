from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.account_snapshot import AccountSnapshot


@dataclass
class OrderResult:
    order_id: str
    status: str
    filled_qty: float
    avg_price: float
    remaining_qty: float = 0.0


class BrokerClient(Protocol):
    def get_account_snapshot(self) -> AccountSnapshot: ...

    def get_positions(self) -> dict[str, float]: ...

    def place_market_order(self, symbol: str, side: str, quantity: float) -> OrderResult: ...

    def cancel_order(self, order_id: str) -> None: ...

    def supports_fractional(self, symbol: str) -> bool: ...
