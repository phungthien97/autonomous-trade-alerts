from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.picker.windows import filter_hourly_closes, ranking_windows

ET = ZoneInfo("America/New_York")


def test_ranking_windows_fixed_as_of_date() -> None:
    # as_of Sat 2026-10-11 → score 2026-09-11..2026-10-11
    # optimize = 7 days before score start → 2026-09-04..2026-09-10
    windows = ranking_windows(date(2026, 10, 11))
    assert windows.score.start == date(2026, 9, 11)
    assert windows.score.end == date(2026, 10, 11)
    assert windows.optimize.start == date(2026, 9, 4)
    assert windows.optimize.end == date(2026, 9, 10)


def test_ranking_windows_clamps_month_end() -> None:
    windows = ranking_windows(date(2026, 3, 31))
    assert windows.score.end == date(2026, 3, 31)
    assert windows.score.start == date(2026, 2, 28)
    assert windows.optimize.end == date(2026, 2, 27)
    assert windows.optimize.start == date(2026, 2, 21)


def test_ranking_windows_aware_datetime_uses_eastern_date() -> None:
    # 2026-10-12 01:00 UTC = 2026-10-11 21:00 ET → as_of date 2026-10-11
    as_of = datetime(2026, 10, 12, 1, 0, tzinfo=ZoneInfo("UTC"))
    windows = ranking_windows(as_of)
    assert windows.score.end == date(2026, 10, 11)


def test_filter_hourly_closes_inclusive() -> None:
    timestamps = [
        datetime(2026, 9, 10, 15, 30, tzinfo=ET),
        datetime(2026, 9, 11, 10, 30, tzinfo=ET),
        datetime(2026, 9, 12, 10, 30, tzinfo=ET),
        datetime(2026, 10, 11, 15, 30, tzinfo=ET),
        datetime(2026, 10, 12, 10, 30, tzinfo=ET),
    ]
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    ts_out, px_out = filter_hourly_closes(
        timestamps, closes, start=date(2026, 9, 11), end=date(2026, 10, 11)
    )
    assert px_out == [2.0, 3.0, 4.0]
    assert len(ts_out) == 3
