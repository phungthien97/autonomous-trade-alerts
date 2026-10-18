"""Optimize thresholds on one window; score after-fee edge on another."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np

from app.picker.score import score_symbol_series
from app.strategy import optimize_params

MIN_BARS = 2


@dataclass(frozen=True)
class SymbolRankResult:
    skipped: bool
    reason: str = ""
    buy_rise: float | None = None
    sell_drop: float | None = None
    edge: float | None = None
    strategy_return: float | None = None
    bh_return: float | None = None
    strategy_final_value: float | None = None
    bh_final_value: float | None = None
    round_trips: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def rank_one_symbol(
    opt_closes: Sequence[float],
    score_closes: Sequence[float],
    initial_cash: float = 1000.0,
) -> SymbolRankResult:
    """Optimize on ``opt_closes``, score after-fee edge on ``score_closes``."""
    opt = [float(x) for x in opt_closes]
    score = [float(x) for x in score_closes]
    if len(opt) < MIN_BARS:
        return SymbolRankResult(skipped=True, reason="opt_window_too_short")
    if len(score) < MIN_BARS:
        return SymbolRankResult(skipped=True, reason="score_window_too_short")

    try:
        buy_rise, sell_drop, _ = optimize_params(
            train_prices=np.asarray(opt, dtype=float),
            initial_cash=float(initial_cash),
        )
        scored = score_symbol_series(
            score,
            buy_rise=float(buy_rise),
            sell_drop=float(sell_drop),
            initial_cash=float(initial_cash),
        )
    except Exception as exc:  # noqa: BLE001 — surface as skipped for batch ranking
        return SymbolRankResult(skipped=True, reason=f"rank_error:{type(exc).__name__}")

    return SymbolRankResult(
        skipped=False,
        buy_rise=float(buy_rise),
        sell_drop=float(sell_drop),
        edge=float(scored.edge),
        strategy_return=float(scored.strategy_return),
        bh_return=float(scored.bh_return),
        strategy_final_value=float(scored.strategy_final_value),
        bh_final_value=float(scored.bh_final_value),
        round_trips=int(scored.round_trips),
    )
