from __future__ import annotations

from dataclasses import dataclass


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
    """
    cash = max(0.0, float(cash_usd))
    avail = cash if available_funds_usd is None else max(0.0, float(available_funds_usd))
    if gross_position_value_usd is None:
        return min(cash, avail)
    if float(gross_position_value_usd) > 1e-6:
        return min(cash, avail)
    return avail


@dataclass(frozen=True)
class AccountSnapshot:
    """Broker balances used for sizing and never-borrow.

    - cash_usd: TotalCashValue (statement cash; may lag unsettled sells)
    - available_funds_usd: AvailableFunds — broker trading room (may include
      margin against open stock; do not use raw for sizing when long)
    - buying_power_usd: BuyingPower — logged only; never used to authorize buys
    - equity_usd: NetLiquidation (cash + positions + accrued interest, etc.)
    - gross_position_value_usd: GrossPositionValue — stock/ETF market value only
    - accrued_cash_usd: AccruedCash — interest owed/earned, not stock
    - usd_cad_rate: IB ExchangeRate(USD) when base is CAD (CAD per 1 USD);
      amounts above are converted to USD when this was available
    """

    cash_usd: float
    buying_power_usd: float
    equity_usd: float
    available_funds_usd: float | None = None
    gross_position_value_usd: float | None = None
    accrued_cash_usd: float | None = None
    usd_cad_rate: float | None = None

    @property
    def spendable_usd(self) -> float:
        """Funds the bot may use for a BUY (never-borrow)."""
        return compute_spendable(
            self.cash_usd,
            self.available_funds_usd,
            self.gross_position_value_usd,
        )
