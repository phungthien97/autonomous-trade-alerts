import os

from app.broker.gateway import BrokerGateway
from app.broker.memory import InMemoryBroker
from app.live.modes import TradingMode


def test_dry_run_never_submits(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    inner = InMemoryBroker(1000.0, last_prices={"AAPL": 10.0})
    gate = BrokerGateway(inner, TradingMode.live_dry_run)
    result = gate.place_market_order("AAPL", "BUY", 1)
    assert result.status == "dry_run"
    assert gate.submit_count == 0
    assert inner.get_positions() == {}


def test_paper_submits() -> None:
    inner = InMemoryBroker(1000.0, last_prices={"AAPL": 10.0})
    gate = BrokerGateway(inner, TradingMode.broker_paper)
    result = gate.place_market_order("AAPL", "BUY", 1)
    assert result.status == "filled"
    assert gate.submit_count == 1


def test_live_requires_confirm(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    inner = InMemoryBroker(1000.0, last_prices={"AAPL": 10.0})
    gate = BrokerGateway(inner, TradingMode.live)
    assert gate.place_market_order("AAPL", "BUY", 1).status == "rejected"
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "YES")
    assert gate.place_market_order("AAPL", "BUY", 1).status == "filled"
    assert gate.submit_count == 1
    assert os.environ["LIVE_TRADING_CONFIRM"] == "YES"
