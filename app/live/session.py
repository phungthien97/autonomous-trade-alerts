"""US equity regular session helpers.

Holiday coverage is a small configurable set (New Year's Day, Independence Day,
Christmas). It is not a full NYSE calendar — pass ``holidays`` to extend it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# (month, day) observed as closed. Incomplete by design.
DEFAULT_HOLIDAYS: frozenset[tuple[int, int]] = frozenset({(1, 1), (7, 4), (12, 25)})


def _as_utc(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(UTC)


def is_us_equity_rth(
    now_utc: datetime,
    holidays: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
) -> bool:
    """True during Mon–Fri 09:30 inclusive through 16:00 exclusive America/New_York."""
    closed = DEFAULT_HOLIDAYS if holidays is None else holidays
    local = _as_utc(now_utc).astimezone(NY)
    if local.weekday() >= 5:
        return False
    if (local.month, local.day) in closed:
        return False
    open_at = local.replace(hour=9, minute=30, second=0, microsecond=0)
    close_at = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_at <= local < close_at


def next_rth_open(
    now_utc: datetime,
    holidays: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
) -> datetime:
    """Next regular-session open as UTC. If already inside RTH, the following session."""
    closed = DEFAULT_HOLIDAYS if holidays is None else holidays
    local = _as_utc(now_utc).astimezone(NY)
    candidate = local.replace(hour=9, minute=30, second=0, microsecond=0)
    if local >= candidate:
        candidate = candidate + timedelta(days=1)
    for _ in range(14):
        probe = candidate.replace(tzinfo=NY) if candidate.tzinfo is None else candidate
        if probe.weekday() < 5 and (probe.month, probe.day) not in closed:
            return probe.astimezone(UTC)
        candidate = probe + timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    raise RuntimeError("no RTH open found within 14 days")
