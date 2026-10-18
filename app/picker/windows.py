"""Calendar windows for picker optimize (1w) and score (1m) passes.

Bar filter rule (deterministic):
- ``start`` / ``end`` are calendar dates in America/New_York.
- A bar is kept iff its Eastern calendar date satisfies ``start <= date <= end``
  (inclusive on both ends).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date


@dataclass(frozen=True)
class RankingWindows:
    optimize: DateWindow
    score: DateWindow


def _as_et_date(as_of: date | datetime) -> date:
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            raise ValueError("as_of datetime must be timezone-aware")
        return as_of.astimezone(ET).date()
    return as_of


def _minus_one_calendar_month(day: date) -> date:
    """Return the same day-of-month one month earlier (clamp to month end)."""
    year = day.year
    month = day.month - 1
    if month == 0:
        year -= 1
        month = 12
    # Clamp day for shorter months (e.g. Mar 31 -> Feb 28/29)
    for candidate in range(day.day, 0, -1):
        try:
            return date(year, month, candidate)
        except ValueError:
            continue
    raise ValueError(f"Cannot subtract one month from {day}")


def ranking_windows(as_of: date | datetime) -> RankingWindows:
    """Score = latest 1 calendar month ending at as_of; optimize = prior 1 week.

    Optimize window is the 7 calendar days immediately before the score window
    start (inclusive), i.e. ``[score.start - 7d, score.start - 1d]``.
    """
    end = _as_et_date(as_of)
    score_start = _minus_one_calendar_month(end)
    score = DateWindow(start=score_start, end=end)
    opt_end = score_start - timedelta(days=1)
    opt_start = opt_end - timedelta(days=6)
    optimize = DateWindow(start=opt_start, end=opt_end)
    return RankingWindows(optimize=optimize, score=score)


def _bar_et_date(ts: date | datetime) -> date:
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            # Treat naive timestamps as already Eastern wall time.
            return ts.date()
        return ts.astimezone(ET).date()
    return ts


def filter_hourly_closes(
    timestamps: Sequence[date | datetime],
    closes: Sequence[float],
    start: date,
    end: date,
) -> tuple[list[datetime | date], list[float]]:
    """Keep bars whose Eastern calendar date is in ``[start, end]`` inclusive."""
    if len(timestamps) != len(closes):
        raise ValueError("timestamps and closes must have the same length")
    out_ts: list[datetime | date] = []
    out_px: list[float] = []
    for ts, px in zip(timestamps, closes):
        d = _bar_et_date(ts)
        if start <= d <= end:
            out_ts.append(ts)
            out_px.append(float(px))
    return out_ts, out_px
