from __future__ import annotations

from enum import Enum


class TradingMode(str, Enum):
    sim = "sim"
    broker_paper = "broker_paper"
    live_dry_run = "live_dry_run"
    live = "live"


def parse_mode(raw: str) -> TradingMode:
    try:
        return TradingMode(raw)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in TradingMode)
        raise ValueError(f"Unknown trading mode {raw!r}; expected one of: {allowed}") from exc
