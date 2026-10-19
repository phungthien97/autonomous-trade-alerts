"""CLI: weekend S&P 500 ranking job.

Usage:
  python -m app.picker_rank --dry-run
  python -m app.picker_rank --as-of 2026-10-11 --no-email
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import urlopen

from app.paths import PickerPaths, ROOT
from app.picker.active import load_active
from app.picker.ibkr_bars import IbkrHourlyBarProvider
from app.picker.run import run_ranking
from app.picker.sp500 import load_sp500_constituents, profiles_by_symbol

ET = ZoneInfo("America/New_York")
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _parse_as_of(raw: str | None) -> date:
    if not raw:
        return datetime.now(tz=ET).date()
    return date.fromisoformat(raw)


def _wiki_fetcher() -> str:
    # Wikipedia blocks bare urllib user-agents with HTTP 403.
    from urllib.request import Request

    req = Request(
        WIKI_URL,
        headers={
            "User-Agent": (
                "autonomous-trade-alerts/1.0 "
                "(S&P constituent cache; local trading bot)"
            ),
            "Accept": "text/html",
        },
    )
    with urlopen(req, timeout=60) as resp:  # noqa: S310 — public Wikipedia
        return resp.read().decode("utf-8", errors="replace")


def _fixture_provider_from_env():
    """CI escape hatch: PICKER_FIXTURE_BARS=path.json mapping symbol -> [[iso, close], ...]."""
    path = os.environ.get("PICKER_FIXTURE_BARS")
    if not path:
        return None
    import json
    from datetime import datetime as dt

    from app.picker.bars import FixtureBarProvider

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    series = {}
    for symbol, rows in raw.items():
        series[symbol] = [
            (dt.fromisoformat(ts.replace("Z", "+00:00")), float(px)) for ts, px in rows
        ]
    return FixtureBarProvider(series=series)


def _recent_successful_run(picker_paths: PickerPaths, within_days: int = 13) -> Path | None:
    runs = picker_paths.ranking_runs_dir
    if not runs.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = 0.0
    for path in runs.glob("*.json"):
        try:
            payload = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if '"aborted": true' in payload or '"aborted":true' in payload:
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = path
    if newest is None:
        return None
    age_days = (datetime.now().timestamp() - newest_mtime) / 86400.0
    if age_days <= within_days:
        return newest
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Biweekly S&P 500 picker ranking")
    parser.add_argument("--dry-run", action="store_true", help="Write report only; no pending")
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD (Eastern calendar date)")
    parser.add_argument("--no-email", action="store_true", help="Skip SMTP send")
    parser.add_argument("--force", action="store_true", help="Ignore biweekly skip window")
    parser.add_argument(
        "--project-root",
        default=None,
        help="Override project root (default: repo root)",
    )
    args = parser.parse_args(argv)

    root = Path(args.project_root) if args.project_root else ROOT
    picker_paths = PickerPaths(project_root=root)
    as_of = _parse_as_of(args.as_of)

    force = args.force or os.environ.get("PICKER_FORCE") == "1"
    if not force and not args.dry_run:
        recent = _recent_successful_run(picker_paths)
        if recent is not None:
            print(f"skip_biweekly recent_run={recent.name}")
            return 0
    active = load_active(picker_paths.active_selection_path)
    active_symbols = [s.symbol for s in active.symbols if not s.exit_only] if active else []

    fixture = _fixture_provider_from_env()
    if fixture is not None:
        provider = fixture
        print("bar_provider=fixture_env")
    else:
        from app.broker.ibkr import IbkrBroker

        port = int(os.environ.get("IB_PORT", "4002"))
        # Prefer dedicated picker client id so we do not fight live-worker (1).
        if "IB_CLIENT_ID" not in os.environ:
            os.environ["IB_CLIENT_ID"] = os.environ.get("PICKER_IB_CLIENT_ID", "7")
        client_id = int(os.environ["IB_CLIENT_ID"])
        broker = IbkrBroker(dry_run=True, port=port)
        provider = IbkrHourlyBarProvider(broker)
        print(f"bar_provider=ibkr port={port} client_id={client_id}")

    constituents = load_sp500_constituents(picker_paths.sp500_cache_path, _wiki_fetcher)
    profiles = profiles_by_symbol(constituents)

    def sp500_loader() -> list[str]:
        return [c.symbol for c in constituents]

    result = run_ranking(
        as_of=as_of,
        sp500_loader=sp500_loader,
        bar_provider=provider,
        picker_paths=picker_paths,
        active_symbols=active_symbols,
        send_email=not args.no_email,
        dry_run=args.dry_run,
        profiles=profiles,
    )
    print(f"ok={result.ok} aborted={result.aborted} dry_run={result.dry_run}")
    print(f"run_id={result.run_id} pending_written={result.pending_written}")
    print(f"selected={[s.symbol for s in result.selected]}")
    if result.report_path:
        print(f"report={result.report_path}")
    return 0 if result.ok or result.aborted else 1


if __name__ == "__main__":
    raise SystemExit(main())
