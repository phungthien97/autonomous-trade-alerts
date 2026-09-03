from __future__ import annotations

import numpy as np
import pytest

from app.strategy import (
    build_constrained_grid,
    count_round_trips,
    optimize_params_v2,
    score_params,
    symbol_floor_pct,
)
from tests.fixtures.prices_flat import CHOP, DOWNTREND, INITIAL_CASH, UPTREND


def _default_meta() -> dict:
    return {
        "lambda_per_trip": 10.0,
        "base_floor_pct": 2.0,
        "max_buy_pct": 8.0,
        "min_floor_pct": 1.0,
        "max_floor_pct": 5.0,
        "train_days": 15,
        "validate_days": 5,
    }


def test_constraints_block_extreme_pairs() -> None:
    meta = _default_meta()
    pairs = build_constrained_grid(meta, symbol_vol=0.02, median_vol=0.02)
    assert pairs
    assert all(buy <= 0.08 + 1e-9 for buy, _ in pairs)
    assert all(buy >= 0.02 - 1e-9 for buy, _ in pairs)
    assert all(sell >= buy / 2.0 - 1e-9 for buy, sell in pairs)
    assert not any(abs(buy - 0.115) < 1e-9 and abs(sell - 0.01) < 1e-9 for buy, sell in pairs)


def test_penalty_prefers_fewer_trades() -> None:
    meta = _default_meta()
    final_value = 1000.0
    many_trips = 5
    few_trips = 1
    score_many = final_value - meta["lambda_per_trip"] * many_trips
    score_few = final_value - meta["lambda_per_trip"] * few_trips
    assert score_few > score_many


def test_holdout_rejects_overfit() -> None:
    meta = _default_meta()
    train = UPTREND
    validate = DOWNTREND
    current = (0.01, 0.01)
    buy, sell, _, accepted, reason = optimize_params_v2(
        train_prices=train,
        validate_prices=validate,
        current=current,
        meta=meta,
        initial_cash=INITIAL_CASH,
        symbol_vol=0.02,
        median_vol=0.02,
    )
    assert not accepted
    assert reason == "holdout_rejected"
    assert buy == current[0]
    assert sell == current[1]


def test_holdout_accepts_improvement() -> None:
    meta = {**_default_meta(), "lambda_per_trip": 0.0}
    train = CHOP
    validate = CHOP
    current = (0.01, 0.01)
    buy, sell, score, accepted, reason = optimize_params_v2(
        train_prices=train,
        validate_prices=validate,
        current=current,
        meta=meta,
        initial_cash=INITIAL_CASH,
        symbol_vol=0.02,
        median_vol=0.02,
    )
    assert accepted
    assert reason == "applied"
    assert score > score_params(validate, *current, INITIAL_CASH, meta["lambda_per_trip"])


def test_vol_scaling_raises_floor_for_volatile_symbol() -> None:
    meta = _default_meta()
    calm_floor = symbol_floor_pct(meta, symbol_vol=0.01, median_vol=0.02)
    hot_floor = symbol_floor_pct(meta, symbol_vol=0.04, median_vol=0.02)
    assert hot_floor > calm_floor
    calm_grid = build_constrained_grid(meta, symbol_vol=0.01, median_vol=0.02)
    hot_grid = build_constrained_grid(meta, symbol_vol=0.04, median_vol=0.02)
    assert min(b for b, _ in hot_grid) >= min(b for b, _ in calm_grid)
