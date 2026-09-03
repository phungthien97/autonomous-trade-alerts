"""Regression tests for V1 strategy — lock behavior before V2 changes."""

from __future__ import annotations

import numpy as np
import pytest

from app.strategy import StrategyState, optimize_params, run_fixed_params, step_signal
from tests.fixtures.prices_flat import BASELINE, CHOP, DOWNTREND, INITIAL_CASH, UPTREND


def _signal_count(prices: np.ndarray, buy_rise: float, sell_drop: float) -> int:
    state = StrategyState(
        cash=0.0,
        shares=INITIAL_CASH / float(prices[0]),
        peak=float(prices[0]),
        trough=None,
    )
    count = 0
    for price in prices[1:]:
        action, _ = step_signal(state, float(price), buy_rise=buy_rise, sell_drop=sell_drop)
        if action:
            count += 1
    return count


def test_step_signal_sell_on_drop_from_peak() -> None:
    state = StrategyState(cash=0.0, shares=10.0, peak=100.0, trough=None)
    action, reason = step_signal(state, 97.0, buy_rise=0.02, sell_drop=0.02)
    assert action == "SELL"
    assert state.shares == 0.0
    assert state.cash == 970.0
    assert "peak" in reason.lower()


def test_step_signal_buy_on_rise_from_trough() -> None:
    state = StrategyState(cash=1000.0, shares=0.0, peak=None, trough=100.0)
    action, reason = step_signal(state, 103.0, buy_rise=0.02, sell_drop=0.02)
    assert action == "BUY"
    assert state.shares > 0
    assert state.cash == 0.0
    assert "trough" in reason.lower()


def test_optimize_params_uptrend_baseline() -> None:
    expected = BASELINE["uptrend"]
    buy, sell, final = optimize_params(UPTREND, INITIAL_CASH)
    assert buy == pytest.approx(expected["buy_rise"])
    assert sell == pytest.approx(expected["sell_drop"])
    assert final == pytest.approx(expected["final_value"])
    assert _signal_count(UPTREND, buy, sell) == expected["signal_count"]


def test_optimize_params_downtrend_baseline() -> None:
    expected = BASELINE["downtrend"]
    buy, sell, final = optimize_params(DOWNTREND, INITIAL_CASH)
    assert buy == pytest.approx(expected["buy_rise"])
    assert sell == pytest.approx(expected["sell_drop"])
    assert final == pytest.approx(expected["final_value"])
    assert _signal_count(DOWNTREND, buy, sell) == expected["signal_count"]


def test_optimize_params_chop_baseline() -> None:
    expected = BASELINE["chop"]
    buy, sell, final = optimize_params(CHOP, INITIAL_CASH)
    assert buy == pytest.approx(expected["buy_rise"])
    assert sell == pytest.approx(expected["sell_drop"])
    assert final == pytest.approx(expected["final_value"], abs=0.15)
    assert _signal_count(CHOP, buy, sell) == expected["signal_count"]


def test_run_fixed_params_matches_step_signal_loop() -> None:
    buy, sell = 0.03, 0.04
    simulated = run_fixed_params(CHOP, buy_rise=buy, sell_drop=sell, initial_cash=INITIAL_CASH)
    state = StrategyState(
        cash=0.0,
        shares=INITIAL_CASH / float(CHOP[0]),
        peak=float(CHOP[0]),
        trough=None,
    )
    for price in CHOP[1:]:
        step_signal(state, float(price), buy_rise=buy, sell_drop=sell)
    assert simulated == state.cash + state.shares * float(CHOP[-1])
