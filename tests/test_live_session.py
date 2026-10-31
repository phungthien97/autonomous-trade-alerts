from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.live import is_us_equity_rth, next_rth_open
from app.live.session import is_nyse_holiday, nyse_holidays_for_year

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _utc(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NY).astimezone(UTC)


def test_rth_true_inside_session() -> None:
    # Wednesday 2026-09-23 10:00 ET
    assert is_us_equity_rth(_utc(2026, 9, 23, 10, 0)) is True


def test_rth_false_before_open_and_at_close() -> None:
    assert is_us_equity_rth(_utc(2026, 9, 23, 9, 29)) is False
    assert is_us_equity_rth(_utc(2026, 9, 23, 9, 30)) is True
    assert is_us_equity_rth(_utc(2026, 9, 23, 16, 0)) is False


def test_rth_false_weekend_and_holiday() -> None:
    # Saturday
    assert is_us_equity_rth(_utc(2026, 9, 26, 11, 0)) is False
    # Christmas
    assert is_us_equity_rth(_utc(2026, 12, 25, 11, 0)) is False
    # Memorial Day 2026 (May 25) — must not look like RTH
    assert is_us_equity_rth(_utc(2026, 5, 25, 11, 0)) is False
    # Thanksgiving 2026 (Nov 26)
    assert is_us_equity_rth(_utc(2026, 11, 26, 11, 0)) is False


def test_nyse_holidays_include_floating_days() -> None:
    days = nyse_holidays_for_year(2026)
    assert date(2026, 1, 1) in days
    assert date(2026, 1, 19) in days  # MLK
    assert date(2026, 5, 25) in days  # Memorial
    assert date(2026, 7, 3) in days  # Independence observed (Sat Jul 4 → Fri)
    assert is_nyse_holiday(date(2026, 4, 3))  # Good Friday 2026


def test_next_open_before_session_is_today() -> None:
    now = _utc(2026, 9, 23, 8, 0)
    opened = next_rth_open(now).astimezone(NY)
    assert opened.hour == 9 and opened.minute == 30
    assert opened.date().isoformat() == "2026-09-23"


def test_next_open_during_session_is_next_day() -> None:
    now = _utc(2026, 9, 23, 10, 0)
    opened = next_rth_open(now).astimezone(NY)
    assert opened.date().isoformat() == "2026-09-24"
    assert opened.hour == 9 and opened.minute == 30


def test_next_open_skips_memorial_day() -> None:
    # Friday May 22 2026 during RTH → next open is Tuesday May 26 (skip weekend + Memorial).
    now = _utc(2026, 5, 22, 10, 0)
    opened = next_rth_open(now).astimezone(NY)
    assert opened.date().isoformat() == "2026-05-26"
