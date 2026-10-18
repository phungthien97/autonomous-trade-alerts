"""Select top symbols from per-symbol ranking results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class SelectedSymbol:
    symbol: str
    edge: float
    strategy_return: float
    buy_rise: float
    sell_drop: float
    bh_return: float | None = None


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def select_symbols(
    results: Sequence[Mapping[str, Any] | Any],
    max_n: int = 5,
) -> list[SelectedSymbol]:
    """Keep non-skipped rows with edge >= 0; top ``max_n`` by edge.

    Tie-break: higher ``strategy_return``, then alphabetical ``symbol``.
    """
    if max_n < 0:
        raise ValueError("max_n must be >= 0")

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

    eligible.sort(key=lambda s: (-s.edge, -s.strategy_return, s.symbol))
    return eligible[:max_n]
