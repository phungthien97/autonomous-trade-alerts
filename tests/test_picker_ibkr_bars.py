from datetime import date, datetime, timezone

from app.picker.ibkr_bars import IbkrHourlyBarProvider


class _FakeBroker:
    def historical_hourly_closes(self, symbol, *, start, end, use_rth=True):
        assert symbol == "AAPL"
        assert use_rth is True
        return [
            (datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc), 100.0),
            (datetime(2026, 9, 11, 14, 30, tzinfo=timezone.utc), 101.0),
        ]


def test_ibkr_hourly_bar_provider_delegates() -> None:
    provider = IbkrHourlyBarProvider(_FakeBroker())
    rows = provider.get_hourly_closes("AAPL", date(2026, 9, 1), date(2026, 9, 30))
    assert [c for _, c in rows] == [100.0, 101.0]
