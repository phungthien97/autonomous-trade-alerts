from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.picker.bars import FixtureBarProvider, fetch_universe_bars
from app.picker.windows import DateWindow

ET = ZoneInfo("America/New_York")


def _series(start: date, days: int, base: float = 100.0) -> list[tuple[datetime, float]]:
    rows: list[tuple[datetime, float]] = []
    px = base
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        rows.append((datetime(d.year, d.month, d.day, 10, 30, tzinfo=ET), px))
        px *= 1.001
    return rows


def test_fetch_universe_abort_when_over_30_percent_skip() -> None:
    opt = DateWindow(start=date(2026, 9, 4), end=date(2026, 9, 10))
    score = DateWindow(start=date(2026, 9, 11), end=date(2026, 10, 11))
    span_start = date(2026, 9, 1)
    symbols = [f"S{i}" for i in range(10)]
    series = {s: _series(span_start, 45, base=100 + i) for i, s in enumerate(symbols)}
    fail = {"S0", "S1", "S2", "S3"}  # 40%
    provider = FixtureBarProvider(series=series, fail_symbols=fail)
    result = fetch_universe_bars(symbols, provider, opt, score, attempts=1)
    assert result.abort is True
    assert len(result.skipped) == 4


def test_fetch_universe_proceeds_under_threshold() -> None:
    opt = DateWindow(start=date(2026, 9, 4), end=date(2026, 9, 10))
    score = DateWindow(start=date(2026, 9, 11), end=date(2026, 10, 11))
    span_start = date(2026, 9, 1)
    symbols = [f"S{i}" for i in range(10)]
    series = {s: _series(span_start, 45, base=100 + i) for i, s in enumerate(symbols)}
    fail = {"S0", "S1"}  # 20%
    provider = FixtureBarProvider(series=series, fail_symbols=fail)
    result = fetch_universe_bars(symbols, provider, opt, score, attempts=1)
    assert result.abort is False
    assert set(result.ok) == set(symbols) - fail
    assert len(result.ok["S5"].opt_closes) >= 2
    assert len(result.ok["S5"].score_closes) >= 2
