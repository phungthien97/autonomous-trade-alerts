from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def compute_spendable(
    cash_usd: float,
    available_funds_usd: float | None,
    gross_position_value_usd: float | None = None,
) -> float:
    """Funds the bot may use for a BUY under never-borrow (Q1.2 / R4).

    - Prefer AvailableFunds when flat: allows same-day unsettled sell credit
      even if TotalCashValue briefly lags (Q2.5).
    - With open stock, AvailableFunds often exceeds cash by the loanable
      portion of those shares (margin). Cap at cash so we never size off
      borrowed buying power. Also min() with AF when AF < cash (cushion).
    - If gross is unknown (None), cap at cash — safer than allowing leverage.

    Amounts are in the broker account currency (see AccountSnapshot.account_currency).
    """
    cash = max(0.0, float(cash_usd))
    avail = cash if available_funds_usd is None else max(0.0, float(available_funds_usd))
    if gross_position_value_usd is None:
        return min(cash, avail)
    if float(gross_position_value_usd) > 1e-6:
        return min(cash, avail)
    return avail


def _norm_ccy(currency: str | None) -> str:
    return str(currency or "USD").upper()


def _rate_for(
    currency: str,
    fx_rates: Mapping[str, float] | None,
    *,
    account_currency: str | None = None,
) -> float | None:
    """BASE units per 1 unit of ``currency`` from the IBKR ledger map.

    Account currency and BASE are treated as 1.0 when they match the bookkeeping
    currency (IBKR quotes other currencies against BASE).
    """
    ccy = _norm_ccy(currency)
    acct = _norm_ccy(account_currency) if account_currency else None
    if ccy in {"BASE", ""} or (acct and ccy == acct):
        return 1.0
    if not fx_rates:
        return None
    raw = fx_rates.get(ccy)
    if raw is None:
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def convert_amount(
    amount: float,
    *,
    from_currency: str,
    to_currency: str,
    fx_rates: Mapping[str, float] | None,
    account_currency: str | None = None,
) -> float:
    """Convert ``amount`` between currencies using IBKR BASE-per-unit rates.

    ``amount_to = amount_from * rate[from] / rate[to]``.

    Same currency → pass through. Missing either rate when currencies differ →
    return 0.0 (block sizing; never treat native cash as the target currency).
    """
    amt = max(0.0, float(amount))
    src = _norm_ccy(from_currency)
    dst = _norm_ccy(to_currency)
    if src == dst:
        return amt
    # BASE and the account bookkeeping currency are aliases when account is BASE.
    acct = _norm_ccy(account_currency) if account_currency else None
    if acct and {src, dst} <= {acct, "BASE"}:
        return amt
    rate_from = _rate_for(src, fx_rates, account_currency=account_currency)
    rate_to = _rate_for(dst, fx_rates, account_currency=account_currency)
    if rate_from is None or rate_to is None:
        return 0.0
    return amt * rate_from / rate_to


def to_usd(
    amount: float,
    *,
    account_currency: str,
    usd_cad_rate: float | None = None,
    fx_rates: Mapping[str, float] | None = None,
) -> float:
    """Convert account-currency amount to USD for US equity share sizing.

    Prefer ``fx_rates`` (full IBKR ledger map). ``usd_cad_rate`` remains as a
    compatibility shim when only the USD leg is known (CAD/BASE accounts).
    """
    ccy = _norm_ccy(account_currency)
    rates: dict[str, float] | None
    if fx_rates:
        rates = {str(k).upper(): float(v) for k, v in fx_rates.items() if float(v) > 0}
    elif usd_cad_rate is not None and float(usd_cad_rate) > 0 and ccy in {"CAD", "BASE"}:
        rates = {"USD": float(usd_cad_rate), "BASE": 1.0, ccy: 1.0}
    else:
        rates = None
    return convert_amount(
        amount,
        from_currency=ccy,
        to_currency="USD",
        fx_rates=rates,
        account_currency=ccy,
    )


def derive_usd_cad_rate(
    fx_rates: Mapping[str, float] | None,
    *,
    account_currency: str | None = None,
) -> float | None:
    """Compat: BASE (or CAD account) units per 1 USD from the ledger map."""
    if not fx_rates:
        return None
    usd = fx_rates.get("USD")
    if usd is None:
        return None
    try:
        rate = float(usd)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


@dataclass(frozen=True)
class AccountSnapshot:
    """Broker balances used for sizing and never-borrow.

    Field names keep a ``_usd`` suffix for history, but cash/equity/gross/AF
    values are in ``account_currency`` from IBKR (often CAD on Canada paper).
    Do not convert those for display or the daily NAV log — that breaks Day P&L.

    For US equity buys, use ``spendable_usd`` which converts account currency→USD
    via ``fx_rates`` (IBKR ledger map) so share qty matches USD prices.
    """

    cash_usd: float
    buying_power_usd: float
    equity_usd: float
    available_funds_usd: float | None = None
    gross_position_value_usd: float | None = None
    accrued_cash_usd: float | None = None
    account_currency: str = "USD"
    usd_cad_rate: float | None = None
    fx_rates: dict[str, float] | None = None

    @property
    def spendable_native(self) -> float:
        """Never-borrow pool in account currency (CAD on Canada paper)."""
        return compute_spendable(
            self.cash_usd,
            self.available_funds_usd,
            self.gross_position_value_usd,
        )

    @property
    def spendable_usd(self) -> float:
        """Never-borrow pool in USD for US share prices / debit checks."""
        return to_usd(
            self.spendable_native,
            account_currency=self.account_currency,
            usd_cad_rate=self.usd_cad_rate,
            fx_rates=self.fx_rates,
        )
