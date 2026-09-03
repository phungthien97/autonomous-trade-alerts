from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# US Eastern Time (EST/EDT via IANA America/New_York).
DISPLAY_TZ = ZoneInfo("America/New_York")
WEEKLY_SEND_HOUR = 10
WEEKLY_SEND_WEEKDAY = 5  # Saturday


def now_display() -> datetime:
    return datetime.now(DISPLAY_TZ)


def format_display(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S %Z") -> str:
    if dt is None:
        return "Never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(DISPLAY_TZ).strftime(fmt)


def should_send_weekly_now(now: datetime | None = None) -> bool:
    now = now or now_display()
    local = now.astimezone(DISPLAY_TZ)
    return local.weekday() == WEEKLY_SEND_WEEKDAY and local.hour == WEEKLY_SEND_HOUR
