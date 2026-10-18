"""IBKR-backed hourly bar provider for picker ranking."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Sequence


class IbkrHourlyBarProvider:
    """``HourlyBarProvider`` using ``broker.historical_hourly_closes``."""

    def __init__(self, broker: Any) -> None:
        self.broker = broker

    def get_hourly_closes(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> Sequence[tuple[datetime | date, float]]:
        if not hasattr(self.broker, "historical_hourly_closes"):
            raise AttributeError("broker must implement historical_hourly_closes")
        return list(
            self.broker.historical_hourly_closes(
                symbol, start=start, end=end, use_rth=True
            )
        )
