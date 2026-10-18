from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.picker.bars import FixtureBarProvider, SkipSymbol, fetch_symbol_with_retries

ET = ZoneInfo("America/New_York")


def test_fixture_provider_returns_filtered_bars() -> None:
    series = {
        "AAPL": [
            (datetime(2026, 9, 1, 10, 30, tzinfo=ET), 100.0),
            (datetime(2026, 9, 10, 10, 30, tzinfo=ET), 101.0),
            (datetime(2026, 9, 15, 10, 30, tzinfo=ET), 102.0),
        ]
    }
    provider = FixtureBarProvider(series=series)
    rows = provider.get_hourly_closes("AAPL", date(2026, 9, 10), date(2026, 9, 15))
    assert [c for _, c in rows] == [101.0, 102.0]


def test_fetch_symbol_with_retries_then_skip() -> None:
    provider = FixtureBarProvider(series={}, fail_symbols={"MSFT"})
    with pytest.raises(SkipSymbol) as exc:
        fetch_symbol_with_retries(
            provider, "MSFT", date(2026, 9, 1), date(2026, 9, 30), attempts=3
        )
    assert exc.value.symbol == "MSFT"
    assert exc.value.reason == "ConnectionError"
