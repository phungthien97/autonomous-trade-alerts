from app.broker import InMemoryBroker


def test_buy_then_sell() -> None:
    broker = InMemoryBroker(cash_usd=1000.0, last_prices={"AAPL": 100.0})
    buy = broker.place_market_order("AAPL", "BUY", 2.0)
    assert buy.status == "filled"
    assert broker.get_positions()["AAPL"] == 2.0
    assert broker.get_account_snapshot().cash_usd == 800.0
    sell = broker.place_market_order("AAPL", "SELL", 2.0)
    assert sell.status == "filled"
    assert broker.get_positions()["AAPL"] == 0.0
    assert broker.get_account_snapshot().cash_usd == 1000.0


def test_insufficient_cash_rejected() -> None:
    broker = InMemoryBroker(cash_usd=50.0, last_prices={"MSFT": 100.0})
    result = broker.place_market_order("MSFT", "BUY", 1.0)
    assert result.status == "rejected"
    assert result.filled_qty == 0.0
    assert broker.get_positions() == {}


def test_fractional_flag() -> None:
    broker = InMemoryBroker(100.0, fractional=False)
    assert broker.supports_fractional("AAPL") is False
    broker_frac = InMemoryBroker(100.0, fractional=True)
    assert broker_frac.supports_fractional("SMH") is True
