from types import SimpleNamespace

import pytest

from app.account_snapshot import AccountSnapshot
from app.broker.ibkr import IbkrBroker, connection_settings


class _FakeIB:
    def __init__(self) -> None:
        self.placed = []
        self.cancelled = []
        self._positions = [
            SimpleNamespace(contract=SimpleNamespace(symbol="AAPL"), position=2.5),
            SimpleNamespace(contract=SimpleNamespace(symbol="MSFT"), position=1.0),
        ]
        self._values = [
            SimpleNamespace(tag="TotalCashValue", value="800", currency="USD"),
            SimpleNamespace(tag="AvailableFunds", value="850", currency="USD"),
            SimpleNamespace(tag="BuyingPower", value="1600", currency="USD"),
            SimpleNamespace(tag="NetLiquidation", value="1200", currency="USD"),
            SimpleNamespace(tag="TotalCashValue", value="999", currency="CAD"),
        ]

    def positions(self):
        return self._positions

    def accountValues(self):
        return self._values

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        return SimpleNamespace(
            order=SimpleNamespace(orderId=42),
            orderStatus=SimpleNamespace(status="Filled", filled=order.totalQuantity, remaining=0, avgFillPrice=100),
        )

    def openTrades(self):
        return []

    def cancelOrder(self, order):
        self.cancelled.append(order)


def test_maps_positions_and_usd_account() -> None:
    broker = IbkrBroker(ib=_FakeIB())
    assert broker.get_positions() == {"AAPL": 2.5, "MSFT": 1.0}
    snap = broker.get_account_snapshot()
    assert isinstance(snap, AccountSnapshot)
    assert snap.cash_usd == 800
    assert snap.available_funds_usd == 850
    # No GrossPositionValue tag → unknown longs → cap at cash (never-borrow)
    assert snap.spendable_usd == 800
    assert snap.buying_power_usd == 1600
    assert snap.equity_usd == 1200
    # API cannot place fractional US equity orders (IBKR Error 10243) — R3 2026-10-07
    assert broker.supports_fractional("AAPL") is False
    assert broker.supports_fractional("MSFT") is False
    assert broker.supports_fractional("ZZZ") is False


def test_supports_fractional_can_be_overridden() -> None:
    broker = IbkrBroker(ib=_FakeIB(), fractional_symbols={"AAPL"})
    assert broker.supports_fractional("AAPL") is True
    assert broker.supports_fractional("MSFT") is False


def test_cad_paper_account_fallback() -> None:
    fake = _FakeIB()
    fake._values = [
        SimpleNamespace(tag="TotalCashValue", value="1000000", currency="CAD"),
        SimpleNamespace(tag="AvailableFunds", value="1000042.91", currency="CAD"),
        SimpleNamespace(tag="BuyingPower", value="3333333.33", currency="CAD"),
        SimpleNamespace(tag="NetLiquidation", value="1000000", currency="CAD"),
        SimpleNamespace(tag="GrossPositionValue", value="0", currency="CAD"),
    ]
    snap = IbkrBroker(ib=fake).get_account_snapshot()
    assert snap.cash_usd == 1_000_000
    assert snap.available_funds_usd == pytest.approx(1_000_042.91)
    # Flat: AF allowed in native CAD, but USD sizing blocked without FX rate.
    assert snap.spendable_native == pytest.approx(1_000_042.91)
    assert snap.spendable_usd == 0.0
    assert snap.account_currency == "CAD"
    assert snap.buying_power_usd == 3_333_333.33
    assert snap.equity_usd == 1_000_000
    assert snap.gross_position_value_usd == 0.0
    assert snap.accrued_cash_usd is None


def test_long_cad_caps_spendable_and_converts_fx() -> None:
    fake = _FakeIB()
    fake._values = [
        SimpleNamespace(tag="TotalCashValue", value="313012.93", currency="CAD"),
        SimpleNamespace(tag="AvailableFunds", value="757902.61", currency="CAD"),
        SimpleNamespace(tag="BuyingPower", value="2500000", currency="CAD"),
        SimpleNamespace(tag="NetLiquidation", value="977505.57", currency="CAD"),
        SimpleNamespace(tag="GrossPositionValue", value="663699.32", currency="CAD"),
        SimpleNamespace(tag="AccruedCash", value="793.33", currency="CAD"),
        # Canada paper uses $LEDGER-ExchangeRate, not plain ExchangeRate.
        SimpleNamespace(tag="$LEDGER-ExchangeRate", value="1.41", currency="USD"),
    ]
    snap = IbkrBroker(ib=fake).get_account_snapshot()
    assert snap.usd_cad_rate == pytest.approx(1.41)
    assert snap.fx_rates is not None
    assert snap.fx_rates.get("USD") == pytest.approx(1.41)
    assert snap.fx_rates.get("CAD") == pytest.approx(1.0)
    # Portfolio stays CAD (Day P&L / NAV log); share sizing uses USD spendable.
    assert snap.account_currency == "CAD"
    assert snap.cash_usd == pytest.approx(313_012.93)
    assert snap.available_funds_usd == pytest.approx(757_902.61)
    assert snap.gross_position_value_usd == pytest.approx(663_699.32)
    assert snap.spendable_native == pytest.approx(313_012.93)
    assert snap.spendable_usd == pytest.approx(313_012.93 / 1.41)


def test_plain_exchange_rate_tag_still_works() -> None:
    fake = _FakeIB()
    fake._values = [
        SimpleNamespace(tag="TotalCashValue", value="1410", currency="CAD"),
        SimpleNamespace(tag="AvailableFunds", value="1410", currency="CAD"),
        SimpleNamespace(tag="BuyingPower", value="1410", currency="CAD"),
        SimpleNamespace(tag="NetLiquidation", value="1410", currency="CAD"),
        SimpleNamespace(tag="GrossPositionValue", value="0", currency="CAD"),
        SimpleNamespace(tag="ExchangeRate", value="1.41", currency="USD"),
    ]
    snap = IbkrBroker(ib=fake).get_account_snapshot()
    assert snap.account_currency == "CAD"
    assert snap.cash_usd == pytest.approx(1410.0)
    assert snap.spendable_usd == pytest.approx(1000.0)


def test_eur_account_converts_via_ledger_map() -> None:
    fake = _FakeIB()
    fake._values = [
        SimpleNamespace(tag="TotalCashValue", value="920", currency="EUR"),
        SimpleNamespace(tag="AvailableFunds", value="920", currency="EUR"),
        SimpleNamespace(tag="BuyingPower", value="920", currency="EUR"),
        SimpleNamespace(tag="NetLiquidation", value="920", currency="EUR"),
        SimpleNamespace(tag="GrossPositionValue", value="0", currency="EUR"),
        SimpleNamespace(tag="$LEDGER-ExchangeRate", value="0.92", currency="USD"),
        SimpleNamespace(tag="$LEDGER-ExchangeRate", value="1.0", currency="BASE"),
    ]
    snap = IbkrBroker(ib=fake).get_account_snapshot()
    assert snap.account_currency == "EUR"
    assert snap.fx_rates is not None
    assert snap.fx_rates.get("USD") == pytest.approx(0.92)
    assert snap.spendable_native == pytest.approx(920.0)
    assert snap.spendable_usd == pytest.approx(1000.0)


def test_gross_position_and_accrued_from_ibkr() -> None:
    fake = _FakeIB()
    fake._values = [
        SimpleNamespace(tag="TotalCashValue", value="969110.33", currency="CAD"),
        SimpleNamespace(tag="AvailableFunds", value="969131.41", currency="CAD"),
        SimpleNamespace(tag="BuyingPower", value="3000000", currency="CAD"),
        SimpleNamespace(tag="NetLiquidation", value="969903.66", currency="CAD"),
        SimpleNamespace(tag="GrossPositionValue", value="0.00", currency="CAD"),
        SimpleNamespace(tag="AccruedCash", value="793.33", currency="CAD"),
    ]
    snap = IbkrBroker(ib=fake).get_account_snapshot()
    assert snap.equity_usd == pytest.approx(969_903.66)
    assert snap.cash_usd == pytest.approx(969_110.33)
    assert snap.gross_position_value_usd == 0.0
    assert snap.accrued_cash_usd == pytest.approx(793.33)
    # Residual equity − cash is accrued interest, not stocks.
    assert snap.equity_usd - snap.cash_usd == pytest.approx(snap.accrued_cash_usd)


def test_cad_converted_with_usd_exchange_rate() -> None:
    fake = _FakeIB()
    fake._values = [
        SimpleNamespace(tag="TotalCashValue", value="1360", currency="CAD"),
        SimpleNamespace(tag="AvailableFunds", value="1360", currency="CAD"),
        SimpleNamespace(tag="BuyingPower", value="1360", currency="BASE"),
        SimpleNamespace(tag="NetLiquidation", value="1360", currency="CAD"),
        SimpleNamespace(tag="GrossPositionValue", value="0", currency="CAD"),
        SimpleNamespace(tag="ExchangeRate", value="1.36", currency="USD"),
    ]
    snap = IbkrBroker(ib=fake).get_account_snapshot()
    assert snap.account_currency == "CAD"
    assert snap.cash_usd == pytest.approx(1360)
    assert snap.equity_usd == pytest.approx(1360)
    assert snap.spendable_usd == pytest.approx(1000)


def test_dry_run_does_not_submit(monkeypatch) -> None:
    fake = _FakeIB()
    monkeypatch.setattr(
        "app.broker.ibkr._market_order",
        lambda symbol, side, quantity: (SimpleNamespace(symbol=symbol), SimpleNamespace(action=side, totalQuantity=quantity)),
    )
    broker = IbkrBroker(ib=fake, dry_run=True)
    result = broker.place_market_order("AAPL", "BUY", 1)
    assert result.status == "dry_run"
    assert fake.placed == []


def test_place_market_order_uses_market_order(monkeypatch) -> None:
    fake = _FakeIB()
    built = {}

    def factory(symbol, side, quantity):
        order = SimpleNamespace(action=side, totalQuantity=quantity)
        contract = SimpleNamespace(symbol=symbol)
        built["order"] = order
        return contract, order

    monkeypatch.setattr("app.broker.ibkr._market_order", factory)
    broker = IbkrBroker(ib=fake)
    result = broker.place_market_order("MSFT", "BUY", 3)
    assert result.status == "filled"
    assert result.filled_qty == 3
    assert result.order_id == "42"
    assert fake.placed[0][0].symbol == "MSFT"
    assert built["order"].action == "BUY"


def test_market_order_day_tif_rth_only(monkeypatch) -> None:
    import types

    import app.broker.ibkr as ibkr_mod

    class _FakeMO:
        def __init__(self, side, quantity, tif="DAY"):
            self.action = side
            self.totalQuantity = quantity
            self.tif = tif
            self.outsideRth = True

    fake_mod = types.ModuleType("ib_insync")
    fake_mod.MarketOrder = _FakeMO  # type: ignore[attr-defined]
    fake_mod.Stock = lambda symbol, *_a, **_k: SimpleNamespace(symbol=symbol)  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "ib_insync", fake_mod)
    _contract, order = ibkr_mod._market_order("FICO", "SELL", 1)
    assert order.tif == "DAY"
    assert order.outsideRth is False


def test_connection_defaults(monkeypatch) -> None:
    monkeypatch.delenv("IB_HOST", raising=False)
    monkeypatch.delenv("IB_PORT", raising=False)
    monkeypatch.delenv("IB_CLIENT_ID", raising=False)
    assert connection_settings() == ("127.0.0.1", 4002, 1)


def test_latest_hourly_closes_rth(monkeypatch) -> None:
    from datetime import datetime, timezone

    class _HistIB(_FakeIB):
        def qualifyContracts(self, contract):
            return [contract]

        def reqHistoricalData(self, *args, **kwargs):
            assert kwargs.get("useRTH") is True
            assert kwargs.get("barSizeSetting") == "1 hour"
            assert kwargs.get("whatToShow") == "TRADES"
            return [
                SimpleNamespace(close=100.0, date=datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)),
                SimpleNamespace(close=101.5, date=datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc)),
            ]

        def sleep(self, _seconds):
            return None

    monkeypatch.setattr(
        "app.broker.ibkr._stock_contract",
        lambda symbol: SimpleNamespace(symbol=symbol, exchange="SMART", currency="USD"),
    )
    prices, bars, closes = IbkrBroker(ib=_HistIB()).latest_hourly_closes(["AAPL"])
    assert prices == {"AAPL": 101.5}
    assert bars["AAPL"].startswith("2026-10-07T19:00:00")
    assert closes == {"AAPL": [100.0, 101.5]}
