"""Simulate IBKR submitted-then-disconnect race that stranded NCLH.

Root cause (Nov 3): place_market_order returned on first Submitted snapshot;
oneshot live-worker then ib.disconnect(), which cancels unfilled DAY orders.
Liquid names often filled in that window; NCLH (large lot) repeatedly did not.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.broker.ibkr import IbkrBroker


@pytest.fixture(autouse=True)
def _stub_market_order(monkeypatch):
    """Avoid importing real ib_insync.MarketOrder (event-loop side effects)."""

    def factory(symbol, side, quantity):
        return (
            SimpleNamespace(symbol=symbol),
            SimpleNamespace(action=side, totalQuantity=quantity, tif="DAY", outsideRth=False),
        )

    monkeypatch.setattr("app.broker.ibkr._market_order", factory)


class _SlowFillIB:
    """Order stays Submitted for N polls, then Fills (or never)."""

    def __init__(self, *, fill_after_polls: int | None = 3) -> None:
        self.fill_after = fill_after_polls
        self.polls = 0
        self.placed = []
        self.cancelled = []
        self._trade = None

    def qualifyContracts(self, contract):
        return [contract]

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        self._trade = SimpleNamespace(
            order=SimpleNamespace(orderId=77),
            orderStatus=SimpleNamespace(
                status="Submitted",
                filled=0.0,
                remaining=float(order.totalQuantity),
                avgFillPrice=0.0,
            ),
        )
        return self._trade

    def sleep(self, _seconds: float) -> None:
        self.polls += 1
        if self._trade is None:
            return
        if self.fill_after is not None and self.polls >= self.fill_after:
            qty = float(self._trade.orderStatus.remaining or 0.0) + float(
                self._trade.orderStatus.filled or 0.0
            )
            self._trade.orderStatus.status = "Filled"
            self._trade.orderStatus.filled = qty
            self._trade.orderStatus.remaining = 0.0
            self._trade.orderStatus.avgFillPrice = 17.5

    def openTrades(self):
        if self._trade is None:
            return []
        return [self._trade]

    def cancelOrder(self, order):
        self.cancelled.append(order)
        if self._trade is not None:
            self._trade.orderStatus.status = "Cancelled"


def test_place_market_order_waits_until_filled() -> None:
    ib = _SlowFillIB(fill_after_polls=3)
    broker = IbkrBroker(ib=ib)
    result = broker.place_market_order("NCLH", "SELL", 3228)
    assert result.status == "filled"
    assert result.filled_qty == 3228
    assert ib.polls >= 3
    assert ib.cancelled == []


def test_place_market_order_timeout_cancels_unfilled() -> None:
    ib = _SlowFillIB(fill_after_polls=None)  # never fills
    broker = IbkrBroker(ib=ib)
    result = broker.place_market_order(
        "NCLH",
        "SELL",
        3228,
        wait_timeout_sec=0.35,
        poll_sec=0.05,
    )
    assert result.status == "cancelled"
    assert result.filled_qty == 0.0
    assert ib.cancelled  # must cancel before disconnect would


def test_place_market_order_rejects_unqualified_contract() -> None:
    class _NoQualify(_SlowFillIB):
        def qualifyContracts(self, contract):
            return []

    broker = IbkrBroker(ib=_NoQualify())
    result = broker.place_market_order("NCLH", "SELL", 1)
    assert result.status == "rejected"
    assert result.filled_qty == 0.0
