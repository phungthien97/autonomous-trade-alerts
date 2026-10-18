"""First-entry trend gate: price must be above the 20-hour SMA."""

from __future__ import annotations

from typing import Sequence


def sma(closes: Sequence[float], window: int = 20) -> float | None:
    """Return SMA of the last ``window`` closes, or None if insufficient bars."""
    if window < 1:
        raise ValueError("window must be >= 1")
    if len(closes) < window:
        return None
    tail = [float(x) for x in closes[-window:]]
    return sum(tail) / float(window)


def allow_first_buy(closes: Sequence[float], price: float | None = None, window: int = 20) -> bool:
    """True iff price (default: last close) is strictly above SMA``window``.

    Fail closed when there are fewer than ``window`` bars. Used only while
    ``awaiting_first_buy`` is true on a newly added symbol.
    """
    avg = sma(closes, window=window)
    if avg is None:
        return False
    px = float(closes[-1]) if price is None else float(price)
    return px > avg
