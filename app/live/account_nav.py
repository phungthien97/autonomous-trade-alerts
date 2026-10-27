"""Daily account equity log for Live portfolio performance charts."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_FIELDS = ("date", "equity", "at_utc")


def _eastern_date(at: datetime) -> str:
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(ZoneInfo("America/Toronto")).date().isoformat()


def upsert_account_nav(
    path: Path,
    *,
    equity: float,
    at: datetime | None = None,
) -> None:
    """Write/replace today's equity row (Eastern calendar day)."""
    eq = float(equity)
    if eq <= 0:
        return
    when = at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    day = _eastern_date(when)
    at_utc = when.astimezone(timezone.utc).isoformat()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as handle:
            for raw in csv.DictReader(handle):
                d = str(raw.get("date") or "").strip()
                if not d or d == day:
                    continue
                rows.append(
                    {
                        "date": d,
                        "equity": str(raw.get("equity") or ""),
                        "at_utc": str(raw.get("at_utc") or ""),
                    }
                )
    rows.append({"date": day, "equity": f"{eq:.2f}", "at_utc": at_utc})
    rows.sort(key=lambda r: r["date"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def load_daily_nav(path: Path) -> list[dict[str, Any]]:
    """Return daily equity points with day-over-day change."""
    path = Path(path)
    if not path.is_file():
        return []
    points: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            day = str(raw.get("date") or "").strip()
            if not day:
                continue
            try:
                equity = float(raw["equity"])
            except (KeyError, TypeError, ValueError):
                continue
            points.append({"date": day, "equity": equity, "at_utc": raw.get("at_utc")})
    points.sort(key=lambda r: str(r["date"]))
    out: list[dict[str, Any]] = []
    prev: float | None = None
    for row in points:
        eq = float(row["equity"])
        delta = None if prev is None else eq - prev
        pct = None if prev is None or prev == 0 else (delta / prev) * 100.0
        out.append(
            {
                "date": row["date"],
                "equity": eq,
                "day_change": delta,
                "day_change_pct": pct,
                "at_utc": row.get("at_utc"),
            }
        )
        prev = eq
    return out


def day_pnl_vs_prior_close(
    path: Path,
    *,
    current_equity: float,
    now: datetime | None = None,
) -> tuple[float | None, float | None]:
    """Account day P&L: live equity vs last logged Eastern day before today.

    Uses ``account_nav.csv`` (Eastern calendar dates). Returns ``(delta, pct)``
    or ``(None, None)`` when no prior day exists.
    """
    eq = float(current_equity)
    if eq <= 0:
        return None, None
    when = now or datetime.now(timezone.utc)
    today = _eastern_date(when)
    prior_eq: float | None = None
    for row in reversed(load_daily_nav(path)):
        day = str(row.get("date") or "")
        if day and day < today:
            try:
                prior_eq = float(row["equity"])
            except (TypeError, ValueError, KeyError):
                prior_eq = None
            break
    if prior_eq is None or prior_eq <= 0:
        return None, None
    delta = eq - prior_eq
    pct = (delta / prior_eq) * 100.0
    return delta, pct
