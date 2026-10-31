"""US equity regular session helpers (NYSE RTH + full holiday calendar)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Legacy override shape: (month, day). Prefer ``is_nyse_holiday`` for live gates.
DEFAULT_HOLIDAYS: frozenset[tuple[int, int]] = frozenset({(1, 1), (7, 4), (12, 25)})


def _as_utc(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(UTC)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Nth weekday in month (weekday: Mon=0 … Sun=6)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    """NYSE Saturday→Friday, Sunday→Monday observation for fixed-date holidays."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def nyse_holidays_for_year(year: int) -> frozenset[date]:
    """Full NYSE full-day closures for ``year`` (no early-close half days)."""
    good_friday = _easter_sunday(year) - timedelta(days=2)
    return frozenset(
        {
            _observed(date(year, 1, 1)),  # New Year's Day
            _nth_weekday(year, 1, 0, 3),  # MLK Day
            _nth_weekday(year, 2, 0, 3),  # Presidents Day
            good_friday,
            _last_weekday(year, 5, 0),  # Memorial Day
            _observed(date(year, 6, 19)),  # Juneteenth
            _observed(date(year, 7, 4)),  # Independence Day
            _nth_weekday(year, 9, 0, 1),  # Labor Day
            _nth_weekday(year, 11, 3, 4),  # Thanksgiving
            _observed(date(year, 12, 25)),  # Christmas
        }
    )


def is_nyse_holiday(day: date) -> bool:
    """True when NYSE is closed for a full session on ``day``."""
    return day in nyse_holidays_for_year(day.year)


def _day_closed(
    local_day: date,
    holidays: frozenset[tuple[int, int]] | set[tuple[int, int]] | None,
) -> bool:
    if holidays is not None:
        return (local_day.month, local_day.day) in holidays
    return is_nyse_holiday(local_day)


def is_us_equity_rth(
    now_utc: datetime,
    holidays: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
) -> bool:
    """True during Mon–Fri 09:30 inclusive through 16:00 exclusive America/New_York.

    When ``holidays`` is None, uses the full NYSE calendar (year-aware).
    When provided, uses the legacy (month, day) override set (tests / ops).
    """
    local = _as_utc(now_utc).astimezone(NY)
    if local.weekday() >= 5:
        return False
    if _day_closed(local.date(), holidays):
        return False
    open_at = local.replace(hour=9, minute=30, second=0, microsecond=0)
    close_at = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_at <= local < close_at


def next_rth_open(
    now_utc: datetime,
    holidays: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
) -> datetime:
    """Next regular-session open as UTC. If already inside RTH, the following session."""
    local = _as_utc(now_utc).astimezone(NY)
    candidate = local.replace(hour=9, minute=30, second=0, microsecond=0)
    if local >= candidate:
        candidate = candidate + timedelta(days=1)
    for _ in range(21):
        probe = candidate.replace(tzinfo=NY) if candidate.tzinfo is None else candidate
        if probe.weekday() < 5 and not _day_closed(probe.date(), holidays):
            return probe.astimezone(UTC)
        candidate = probe + timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    raise RuntimeError("no RTH open found within 21 days")
