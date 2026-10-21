"""Sleeve cash budgets: equal re-split (runtime) + priority whole-share allocate (picker)."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Mapping, Sequence


def sleeve_buy_budget(
    spendable_usd: float,
    n_active_non_exit_only: int,
    n_already_long: int,
) -> float:
    """Cash budget for the next BUY among remaining flat active sleeves.

    ``spendable / max(1, n_active - n_already_long)``. No forced rebalance —
    only splits currently available cash across symbols still flat.
    """
    spendable = max(0.0, float(spendable_usd))
    n_active = int(n_active_non_exit_only)
    n_long = int(n_already_long)
    if n_active < 0 or n_long < 0:
        raise ValueError("counts must be non-negative")
    remaining = max(1, n_active - n_long)
    return spendable / float(remaining)


@dataclass(frozen=True)
class SleeveAllocation:
    symbol: str
    price: float
    shares: int
    cash: float


def whole_share_allocation(
    *,
    price: float,
    slot_target: float,
    remaining_cash: float,
) -> tuple[int, float] | None:
    """Whole shares closest to ``slot_target`` without exceeding ``remaining_cash``.

    If even 1 share does not fit in ``slot_target`` but fits in ``remaining_cash``,
    stretch to 1 share (priority top names). Returns ``(shares, cost)`` or None.
    """
    px = float(price)
    if px <= 0 or remaining_cash < px:
        return None
    target = min(float(slot_target), float(remaining_cash))
    shares = int(floor(target / px))
    if shares <= 0:
        shares = 1  # stretch above even-split target when pool allows
    cost = shares * px
    if cost > float(remaining_cash) + 1e-9:
        return None
    return shares, cost


def allocate_priority_sleeves(
    ranked_symbols: Sequence[str],
    prices: Mapping[str, float],
    total_cash: float,
    *,
    max_n: int = 5,
) -> list[SleeveAllocation]:
    """Walk the ranked list; fund up to ``max_n`` buyable whole-share sleeves.

    For each next slot, target = remaining_cash / slots_left. Allocate whole shares
    closest to that target (stretching to 1 share when price > target but still
    affordable). Skip names that cannot buy even 1 share; keep walking the list
    until ``max_n`` sleeves or the list ends (fewer than ``max_n`` is OK).
    """
    if max_n < 0:
        raise ValueError("max_n must be >= 0")
    pool = max(0.0, float(total_cash))
    out: list[SleeveAllocation] = []
    for symbol in ranked_symbols:
        if len(out) >= max_n:
            break
        sym = str(symbol).strip()
        if not sym:
            continue
        try:
            px = float(prices[sym])
        except (KeyError, TypeError, ValueError):
            continue
        slots_left = max_n - len(out)
        slot_target = pool / float(slots_left) if slots_left else 0.0
        got = whole_share_allocation(price=px, slot_target=slot_target, remaining_cash=pool)
        if got is None:
            continue
        shares, cost = got
        out.append(SleeveAllocation(symbol=sym, price=px, shares=shares, cash=cost))
        pool -= cost
    # Park leftover cents/dollars in sleeves so book cash still equals total_cash.
    # (Whole-share costs rarely sum exactly to the book.)
    if out and pool > 1e-9:
        n = len(out)
        each = pool / float(n)
        out = [
            SleeveAllocation(
                symbol=a.symbol,
                price=a.price,
                shares=a.shares,
                cash=round(a.cash + each, 2),
            )
            for a in out
        ]
        # Fix rounding drift on the last sleeve.
        drift = float(total_cash) - sum(a.cash for a in out)
        if abs(drift) >= 0.005:
            last = out[-1]
            out[-1] = SleeveAllocation(
                symbol=last.symbol,
                price=last.price,
                shares=last.shares,
                cash=round(last.cash + drift, 2),
            )
    return out
