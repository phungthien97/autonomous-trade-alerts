"""Synthetic price series for strategy regression tests."""

from __future__ import annotations

import numpy as np

# Steady uptrend: buy-and-hold wins; tight 1%/1% stays invested (no signals).
UPTREND = np.array(
    [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120],
    dtype=float,
)

# Gradual decline: triggers at least one sell with 1%/1% params.
DOWNTREND = np.array([120 - i * 0.5 for i in range(21)], dtype=float)

# Oscillating series: multiple round-trips with tuned params.
CHOP = np.array(
    [100, 102, 99, 103, 98, 104, 97, 105, 96, 106, 95, 107, 94, 108, 93, 109, 92, 110, 91, 111, 90],
    dtype=float,
)

INITIAL_CASH = 1000.0

# Documented V1 baseline outputs (optimize_params on full series, initial_cash=1000).
# Regenerate only if V1 optimizer logic intentionally changes.
BASELINE = {
    "uptrend": {"buy_rise": 0.01, "sell_drop": 0.01, "final_value": 1200.0, "signal_count": 0},
    "downtrend": {"buy_rise": 0.01, "sell_drop": 0.01, "final_value": 987.5, "signal_count": 1},
    "chop": {"buy_rise": 0.01, "sell_drop": 0.14, "final_value": 617.1, "signal_count": 5},
}
