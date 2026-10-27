from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountSnapshot:
    """Broker balances used for sizing and never-borrow.

    - cash_usd: TotalCashValue (statement cash; may lag unsettled sells)
    - available_funds_usd: AvailableFunds — spendable for same-day turnover
      without intentional leverage (R4)
    - buying_power_usd: BuyingPower — logged only; never used to authorize buys
    - equity_usd: NetLiquidation (cash + positions + accrued interest, etc.)
    - gross_position_value_usd: GrossPositionValue — stock/ETF market value only
    - accrued_cash_usd: AccruedCash — interest owed/earned, not stock
    """

    cash_usd: float
    buying_power_usd: float
    equity_usd: float
    available_funds_usd: float | None = None
    gross_position_value_usd: float | None = None
    accrued_cash_usd: float | None = None

    @property
    def spendable_usd(self) -> float:
        """Funds the bot may use for a BUY (AvailableFunds, else cash)."""
        if self.available_funds_usd is not None:
            return float(self.available_funds_usd)
        return float(self.cash_usd)
