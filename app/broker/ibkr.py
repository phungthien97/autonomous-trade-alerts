"""IBKR adapter via ib_insync.

A running IB Gateway (or TWS) must be up for real connections. Paper default
is 127.0.0.1:4002. Unit tests inject a fake client and never place orders.
"""

from __future__ import annotations

import os

from app.account_snapshot import AccountSnapshot, derive_usd_cad_rate
from app.broker.base import OrderResult

# IBKR may advertise sizeIncrement < 1 for US stocks, but the socket API rejects
# fractional equity orders with Error 10243 ("use desktop version"). Keep empty
# so live/paper API path sizes in whole shares; leftover cash stays cash (Q2.4).
DEFAULT_FRACTIONAL: frozenset[str] = frozenset()


def connection_settings() -> tuple[str, int, int]:
    host = os.environ.get("IB_HOST", "127.0.0.1")
    port = int(os.environ.get("IB_PORT", "4002"))
    client_id = int(os.environ.get("IB_CLIENT_ID", "1"))
    return host, port, client_id


class IbkrBroker:
    def __init__(
        self,
        ib=None,
        fractional_symbols: set[str] | frozenset[str] | None = None,
        dry_run: bool = False,
        port: int | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.fractional_symbols = set(DEFAULT_FRACTIONAL if fractional_symbols is None else fractional_symbols)
        if ib is None:
            from ib_insync import IB

            host, default_port, client_id = connection_settings()
            self.ib = IB()
            self.ib.connect(host, port if port is not None else default_port, clientId=client_id)
        else:
            self.ib = ib

    def get_positions(self) -> dict[str, float]:
        positions: dict[str, float] = {}
        for pos in self.ib.positions():
            positions[pos.contract.symbol] = float(pos.position)
        return positions

    def get_account_snapshot(self) -> AccountSnapshot:
        """Map IB account values into snapshot fields (IBKR currency preserved).

        Preference: USD tags, then blank currency, then BASE/CAD (Canada paper).
        Non-USD amounts are converted with ExchangeRate(USD) when IB provides it
        (base-currency units per 1 USD) and labeled USD; otherwise the native
        IBKR currency is kept (often CAD) so we never pretend CAD is USD.
        """
        by_tag: dict[str, dict[str, float]] = {}
        for item in self.ib.accountValues():
            try:
                value = float(item.value)
            except (TypeError, ValueError):
                continue
            currency = item.currency or ""
            by_tag.setdefault(item.tag, {})[currency] = value

        cash, account_ccy = _pick_account_amount(by_tag, "TotalCashValue")
        available, avail_ccy = _pick_account_amount(by_tag, "AvailableFunds")
        if available <= 0:
            available, avail_ccy = cash, account_ccy
        # GrossPositionValue / AccruedCash may be absent on older stubs; treat
        # missing tags as 0 so flat paper accounts do not invent "stocks".
        has_gross = "GrossPositionValue" in by_tag
        has_accrued = "AccruedCash" in by_tag
        equity, eq_ccy = _pick_account_amount(by_tag, "NetLiquidation")
        bp, _bp_ccy = _pick_account_amount(by_tag, "BuyingPower")
        gross = None
        if has_gross:
            gross, _g = _pick_account_amount(by_tag, "GrossPositionValue")
        accrued = None
        if has_accrued:
            accrued, _a = _pick_account_amount(by_tag, "AccruedCash")
        # Prefer NetLiquidation currency as the bookkeeping currency.
        account_currency = eq_ccy or account_ccy or avail_ccy or "USD"
        fx_rates = _ledger_fx_rates(by_tag, account_currency=account_currency)
        usd_rate = derive_usd_cad_rate(fx_rates, account_currency=account_currency)
        return AccountSnapshot(
            cash_usd=cash,
            buying_power_usd=bp,
            equity_usd=equity,
            available_funds_usd=available,
            gross_position_value_usd=gross,
            accrued_cash_usd=accrued,
            account_currency=account_currency,
            usd_cad_rate=float(usd_rate) if usd_rate is not None and float(usd_rate) > 0 else None,
            fx_rates=fx_rates or None,
        )

    def supports_fractional(self, symbol: str) -> bool:
        return symbol in self.fractional_symbols

    def place_market_order(self, symbol: str, side: str, quantity: float, dry_run: bool | None = None) -> OrderResult:
        is_dry = self.dry_run if dry_run is None else dry_run
        contract, order = _market_order(symbol, side, quantity)
        if is_dry:
            return OrderResult(order_id="dry", status="dry_run", filled_qty=0.0, avg_price=0.0, remaining_qty=0.0)
        trade = self.ib.placeOrder(contract, order)
        status_obj = trade.orderStatus
        status = str(getattr(status_obj, "status", "submitted")).lower()
        filled = float(getattr(status_obj, "filled", 0.0) or 0.0)
        remaining = float(getattr(status_obj, "remaining", 0.0) or 0.0)
        avg = float(getattr(status_obj, "avgFillPrice", 0.0) or 0.0)
        order_id = str(getattr(trade.order, "orderId", ""))
        mapped = _map_status(status, filled, remaining)
        if mapped == "partial" and remaining > 0:
            self.cancel_order(order_id)
            remaining = 0.0
        return OrderResult(order_id, mapped, filled, avg, remaining)

    def cancel_order(self, order_id: str) -> None:
        for trade in self.ib.openTrades():
            if str(getattr(trade.order, "orderId", "")) == str(order_id):
                self.ib.cancelOrder(trade.order)
                return

    def latest_hourly_closes(
        self,
        symbols: list[str],
        *,
        use_rth: bool = True,
        duration: str = "5 D",
    ) -> tuple[dict[str, float], dict[str, str], dict[str, list[float]]]:
        """Latest TRADES hourly bar close per symbol (RTH by default — R6).

        Uses complimentary IBKR US historical data when entitled. Returns
        ({symbol: close}, {symbol: bar_ts_iso}, {symbol: close_series}).
        Missing symbols are omitted. ``close_series`` feeds the first-buy SMA gate.
        """
        prices: dict[str, float] = {}
        bars: dict[str, str] = {}
        closes: dict[str, list[float]] = {}
        for symbol in symbols:
            contract = _stock_contract(symbol)
            qualified = self.ib.qualifyContracts(contract)
            if not qualified:
                continue
            hist = self.ib.reqHistoricalData(
                qualified[0],
                endDateTime="",
                durationStr=duration,
                barSizeSetting="1 hour",
                whatToShow="TRADES",
                useRTH=use_rth,
                formatDate=2,
                keepUpToDate=False,
            )
            if hasattr(self.ib, "sleep"):
                self.ib.sleep(0.5)
            if not hist:
                continue
            series = [float(bar.close) for bar in hist]
            closes[symbol] = series
            last = hist[-1]
            prices[symbol] = float(last.close)
            date = last.date
            if hasattr(date, "isoformat"):
                bars[symbol] = date.isoformat()
            else:
                bars[symbol] = str(date)
        return prices, bars, closes

    def historical_hourly_closes(
        self,
        symbol: str,
        *,
        start,
        end,
        use_rth: bool = True,
    ) -> list[tuple]:
        """Hourly TRADES closes for ``symbol`` covering ``[start, end]`` dates.

        Returns list of ``(timestamp, close)``. Empty list if unavailable.
        """
        from datetime import date as date_cls
        from datetime import datetime as datetime_cls
        from datetime import timezone as tz
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        start_d = start if isinstance(start, date_cls) else start
        end_d = end if isinstance(end, date_cls) else end
        days = max(1, (end_d - start_d).days + 7)
        duration = f"{min(days, 365)} D"
        end_dt = datetime_cls(end_d.year, end_d.month, end_d.day, 23, 59, 59, tzinfo=et)
        end_str = end_dt.astimezone(tz.utc).strftime("%Y%m%d %H:%M:%S")

        contract = _stock_contract(symbol)
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            return []
        hist = self.ib.reqHistoricalData(
            qualified[0],
            endDateTime=end_str,
            durationStr=duration,
            barSizeSetting="1 hour",
            whatToShow="TRADES",
            useRTH=use_rth,
            formatDate=2,
            keepUpToDate=False,
        )
        if hasattr(self.ib, "sleep"):
            self.ib.sleep(0.5)
        out: list[tuple] = []
        for bar in hist or []:
            raw = bar.date
            if hasattr(raw, "isoformat"):
                ts = raw if isinstance(raw, datetime_cls) else datetime_cls.fromisoformat(str(raw))
            else:
                ts = datetime_cls.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=tz.utc)
            d = ts.astimezone(et).date()
            if start_d <= d <= end_d:
                out.append((ts, float(bar.close)))
        return out


def _ledger_fx_rates(
    by_tag: dict[str, dict[str, float]],
    *,
    account_currency: str | None = None,
) -> dict[str, float]:
    """IBKR ledger map: BASE units per 1 unit of each quoted currency.

    Merges ``$LEDGER-ExchangeRate`` and ``ExchangeRate`` (ledger wins on clash).
    Account currency and BASE are normalized to 1.0 for convert_amount.
    """
    rates: dict[str, float] = {}
    for tag in ("ExchangeRate", "$LEDGER-ExchangeRate"):
        row = by_tag.get(tag) or {}
        for ccy, raw in row.items():
            key = str(ccy or "BASE").upper()
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                rates[key] = value
    rates["BASE"] = 1.0
    acct = str(account_currency or "").upper()
    if acct and acct != "USD":
        rates.setdefault(acct, 1.0)
    return rates


def _usd_exchange_rate(by_tag: dict[str, dict[str, float]]) -> float | None:
    """Compat: BASE units per 1 USD from the ledger map."""
    return derive_usd_cad_rate(_ledger_fx_rates(by_tag))


def _pick_account_amount(by_tag: dict[str, dict[str, float]], tag: str) -> tuple[float, str]:
    """Return (amount, IBKR currency) without FX conversion.

    Keep native account currency for portfolio display and account_nav Day P&L.
    Callers that size US equities convert via AccountSnapshot.spendable_usd.
    Preference: USD, CAD, BASE, blank, then any other IBKR currency key.
    """
    row = by_tag.get(tag) or {}
    for key, label in (("USD", "USD"), ("CAD", "CAD"), ("BASE", "BASE"), ("", "BASE")):
        if key in row:
            return row[key], label
    for key, value in row.items():
        ccy = str(key or "BASE").upper() or "BASE"
        return value, ccy
    return 0.0, "USD"


def _pick_usd_amount(by_tag: dict[str, dict[str, float]], tag: str) -> float:
    """Amount only (tests / callers that ignore currency)."""
    amount, _ccy = _pick_account_amount(by_tag, tag)
    return amount


def _stock_contract(symbol: str):
    from ib_insync import Stock

    return Stock(symbol, "SMART", "USD")


def _market_order(symbol: str, side: str, quantity: float):
    """US equity market order: DAY TIF, RTH only (avoids IBKR Error 10349).

    Error 10349 fires when a DAY market order is tagged for extended hours /
    overnight. Worker and rebalance already require US RTH; pin outsideRth=False
    so Gateway cannot widen the session.
    """
    from ib_insync import MarketOrder

    order = MarketOrder(side, quantity, tif="DAY")
    order.outsideRth = False
    return _stock_contract(symbol), order


def _map_status(status: str, filled: float, remaining: float) -> str:
    if status in {"cancelled", "apicancelled", "inactive"} and filled <= 0:
        return "cancelled"
    if status in {"cancelled", "apicancelled"} and filled > 0:
        return "partial"
    if remaining > 1e-9 and filled > 0:
        return "partial"
    if status in {"filled"} or (filled > 0 and remaining <= 1e-9):
        return "filled"
    if status in {"rejected"}:
        return "rejected"
    return "submitted"
