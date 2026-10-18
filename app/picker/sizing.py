"""Equal free-cash sleeve budget for soft-rotate entries."""

from __future__ import annotations


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
