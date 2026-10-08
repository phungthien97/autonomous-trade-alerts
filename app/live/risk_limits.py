"""Never-borrow guard.

Same-day turnover may use AvailableFunds (unsettled credit on margin).
BuyingPower (Reg-T leverage) is logged only and never authorizes a buy (R4).
"""

from app.account_snapshot import AccountSnapshot

__all__ = ["AccountSnapshot"]


def would_create_debit(
    side: str,
    notional_usd: float,
    estimated_fees: float,
    snapshot: AccountSnapshot,
) -> bool:
    if side != "BUY":
        return False
    remaining = snapshot.spendable_usd - float(notional_usd) - float(estimated_fees)
    return remaining < -1e-6


def assert_never_borrow(
    side: str,
    notional_usd: float,
    estimated_fees: float,
    snapshot: AccountSnapshot,
) -> None:
    if would_create_debit(side, notional_usd, estimated_fees, snapshot):
        raise ValueError(
            f"BUY of {notional_usd:.2f} plus fees {estimated_fees:.2f} would exceed "
            f"spendable {snapshot.spendable_usd:.2f} "
            f"(cash {snapshot.cash_usd:.2f}; buying power {snapshot.buying_power_usd:.2f} ignored)"
        )
