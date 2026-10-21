"""Select top symbols from per-symbol ranking results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.picker.sizing import allocate_priority_sleeves


@dataclass(frozen=True)
class SelectedSymbol:
    symbol: str
    edge: float
    strategy_return: float
    buy_rise: float
    sell_drop: float
    bh_return: float | None = None
    allocated_cash: float | None = None
    last_price: float | None = None
    shares_budget: int | None = None


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _eligible_ranked(results: Sequence[Mapping[str, Any] | Any]) -> list[SelectedSymbol]:
    eligible: list[SelectedSymbol] = []
    for row in results:
        if bool(_get(row, "skipped", False)):
            continue
        edge = _get(row, "edge")
        if edge is None or float(edge) < 0:
            continue
        symbol = str(_get(row, "symbol", "")).strip()
        if not symbol:
            continue
        buy_rise = _get(row, "buy_rise")
        sell_drop = _get(row, "sell_drop")
        strategy_return = _get(row, "strategy_return")
        if buy_rise is None or sell_drop is None or strategy_return is None:
            continue
        if float(strategy_return) < 0:
            continue
        bh_return = _get(row, "bh_return")
        eligible.append(
            SelectedSymbol(
                symbol=symbol,
                edge=float(edge),
                strategy_return=float(strategy_return),
                buy_rise=float(buy_rise),
                sell_drop=float(sell_drop),
                bh_return=None if bh_return is None else float(bh_return),
            )
        )

    eligible.sort(key=lambda s: (-s.strategy_return, -s.edge, s.symbol))
    return eligible


def select_symbols(
    results: Sequence[Mapping[str, Any] | Any],
    max_n: int = 5,
    *,
    prices: Mapping[str, float] | None = None,
    total_cash: float | None = None,
) -> list[SelectedSymbol]:
    """Keep names that beat B&H and made money; top ``max_n`` by strategy profit.

    Filters: not skipped, ``edge >= 0``, ``strategy_return >= 0``.
    Rank by ``strategy_return`` descending (maximize sleeve dollars).
    Tie-break: higher ``edge``, then alphabetical ``symbol``.

    When ``prices`` and ``total_cash`` are provided, walk the full ranked list and
    assign whole-share sleeve cash (priority stretch for names above the even split).
    May return fewer than ``max_n`` if the list runs out of affordable names.
    """
    if max_n < 0:
        raise ValueError("max_n must be >= 0")

    eligible = _eligible_ranked(results)
    if not prices or total_cash is None:
        return eligible[:max_n]

    by_symbol = {s.symbol: s for s in eligible}
    allocations = allocate_priority_sleeves(
        [s.symbol for s in eligible],
        prices,
        float(total_cash),
        max_n=max_n,
    )
    out: list[SelectedSymbol] = []
    for alloc in allocations:
        base = by_symbol[alloc.symbol]
        out.append(
            SelectedSymbol(
                symbol=base.symbol,
                edge=base.edge,
                strategy_return=base.strategy_return,
                buy_rise=base.buy_rise,
                sell_drop=base.sell_drop,
                bh_return=base.bh_return,
                allocated_cash=alloc.cash,
                last_price=alloc.price,
                shares_budget=alloc.shares,
            )
        )
    return out
