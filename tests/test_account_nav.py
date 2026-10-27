"""Daily account NAV log helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.live.account_nav import day_pnl_vs_prior_close, load_daily_nav, upsert_account_nav


def test_upsert_replaces_same_eastern_day(tmp_path: Path) -> None:
    path = tmp_path / "account_nav.csv"
    morning = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT
    evening = datetime(2026, 10, 22, 22, 0, tzinfo=timezone.utc)  # 18:00 EDT
    upsert_account_nav(path, equity=1_000_000.0, at=morning)
    upsert_account_nav(path, equity=1_005_000.0, at=evening)
    rows = load_daily_nav(path)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-10-22"
    assert rows[0]["equity"] == 1_005_000.0
    assert rows[0]["day_change"] is None


def test_load_daily_nav_day_over_day(tmp_path: Path) -> None:
    path = tmp_path / "account_nav.csv"
    d1 = datetime(2026, 10, 21, 20, 0, tzinfo=ZoneInfo("America/Toronto")).astimezone(timezone.utc)
    d2 = datetime(2026, 10, 22, 20, 0, tzinfo=ZoneInfo("America/Toronto")).astimezone(timezone.utc)
    upsert_account_nav(path, equity=1_000_000.0, at=d1)
    upsert_account_nav(path, equity=1_010_000.0, at=d2)
    rows = load_daily_nav(path)
    assert len(rows) == 2
    assert rows[1]["day_change"] == 10_000.0
    assert abs(float(rows[1]["day_change_pct"]) - 1.0) < 1e-9


def test_day_pnl_vs_prior_close(tmp_path: Path) -> None:
    path = tmp_path / "account_nav.csv"
    d1 = datetime(2026, 10, 25, 20, 0, tzinfo=ZoneInfo("America/Toronto")).astimezone(timezone.utc)
    d2 = datetime(2026, 10, 26, 20, 0, tzinfo=ZoneInfo("America/Toronto")).astimezone(timezone.utc)
    upsert_account_nav(path, equity=969_898.20, at=d1)
    upsert_account_nav(path, equity=977_508.62, at=d2)
    now = datetime(2026, 10, 26, 23, 0, tzinfo=ZoneInfo("America/Toronto")).astimezone(timezone.utc)
    delta, pct = day_pnl_vs_prior_close(path, current_equity=977_508.62, now=now)
    assert delta == 977_508.62 - 969_898.20
    assert abs(float(pct) - ((977_508.62 - 969_898.20) / 969_898.20) * 100.0) < 1e-9
