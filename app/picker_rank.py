"""CLI: weekend S&P 500 ranking job.

Usage:
  python -m app.picker_rank --dry-run
  python -m app.picker_rank --as-of 2026-10-11 --no-email
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import urlopen

from app.live.config import load_live_config
from app.paths import LivePaths, PickerPaths, ROOT
from app.picker.active import load_active
from app.picker.ibkr_bars import IbkrHourlyBarProvider
from app.picker.run import run_ranking
from app.picker.sp500 import load_sp500_constituents, profiles_by_symbol

ET = ZoneInfo("America/New_York")
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Never share live-worker (1) / dashboard (9). .env often sets IB_CLIENT_ID=1 —
# picker must force its own id (and fall back if that slot is busy).
PICKER_CLIENT_ID_DEFAULT = 7
PICKER_CLIENT_ID_FALLBACKS = (7, 17, 27, 37)
PICKER_CONNECT_ATTEMPTS = 4
PICKER_CONNECT_SLEEP_SEC = 15
PICKER_RUN_ATTEMPTS = 3
PICKER_RUN_SLEEP_SEC = 60


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


# Weekly systemd timer + this window ≈ every other Saturday.
# Use 10d (not 13d): a ranking that finishes ~1 day after Saturday midnight
# still leaves the +2-week Saturday eligible. With 13d, that slot skips and
# the next real run slips to ~3 weeks.
BIWEEKLY_SKIP_WITHIN_DAYS = 10


def _recent_successful_run(
    picker_paths: PickerPaths,
    within_days: int = BIWEEKLY_SKIP_WITHIN_DAYS,
    *,
    now_ts: float | None = None,
) -> Path | None:
    """Return newest non-aborted run if it is still inside the skip window.

    ``None`` means the biweekly job should rank (no recent success).
    """
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
    age_days = ((now_ts if now_ts is not None else datetime.now().timestamp()) - newest_mtime) / 86400.0
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
            from datetime import timezone as _tz

            from app.picker.notify import build_skip_email_body, send_picker_email

            now = datetime.now(tz=_tz.utc)
            status = {
                "status": "skipped",
                "reason": "biweekly_window",
                "recent_run": recent.name,
                "within_days": BIWEEKLY_SKIP_WITHIN_DAYS,
                "at_utc": now.isoformat(),
            }
            try:
                picker_paths.state_dir.mkdir(parents=True, exist_ok=True)
                picker_paths.last_rank_status_path.write_text(
                    json.dumps(status, indent=2) + "\n", encoding="utf-8"
                )
            except OSError as exc:
                print(f"warn: could not write last_rank_status: {exc}", file=sys.stderr)
            if not args.no_email:
                body = build_skip_email_body(
                    recent_run=recent.name,
                    within_days=BIWEEKLY_SKIP_WITHIN_DAYS,
                    next_hint="next Saturday after the skip window (or --force)",
                )
                try:
                    send_picker_email("[PICKER] skipped — biweekly window", body)
                except Exception as exc:  # noqa: BLE001
                    print(f"warn: skip email failed: {exc}", file=sys.stderr)
            return 0
    active = load_active(picker_paths.active_selection_path)
    active_symbols = [s.symbol for s in active.symbols if not s.exit_only] if active else []

    book_cash = 1000.0
    live_cfg_path = LivePaths(project_root=root).config_path
    if live_cfg_path.is_file():
        try:
            live_cfg = load_live_config(live_cfg_path)
            if live_cfg.trading_budget_usd is not None:
                book_cash = float(live_cfg.trading_budget_usd)
            else:
                book_cash = float(live_cfg.total_cash)
        except (OSError, TypeError, ValueError, KeyError):
            book_cash = 1000.0

    last_error: str | None = None
    for attempt in range(1, PICKER_RUN_ATTEMPTS + 1):
        broker = None
        try:
            fixture = _fixture_provider_from_env()
            if fixture is not None:
                provider = fixture
                print("bar_provider=fixture_env")
            else:
                broker, client_id, port = _connect_picker_broker()
                provider = IbkrHourlyBarProvider(broker)
                print(f"bar_provider=ibkr port={port} client_id={client_id} attempt={attempt}")

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
                book_cash=book_cash,
                profiles=profiles,
            )
            print(f"ok={result.ok} aborted={result.aborted} dry_run={result.dry_run}")
            print(f"run_id={result.run_id} pending_written={result.pending_written}")
            print(f"selected={[s.symbol for s in result.selected]}")
            if result.report_path:
                print(f"report={result.report_path}")
            _write_rank_status(
                picker_paths,
                {
                    "status": "aborted" if result.aborted else ("dry_run" if result.dry_run else "ran"),
                    "ok": bool(result.ok),
                    "run_id": result.run_id,
                    "pending_written": bool(result.pending_written),
                    "selected": [s.symbol for s in result.selected],
                    "attempt": attempt,
                    "at_utc": datetime.now(tz=timezone.utc).isoformat(),
                },
            )
            return 0 if result.ok or result.aborted else 1
        except Exception as exc:  # noqa: BLE001 — retry connect / ranking crashes
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"picker_rank attempt {attempt}/{PICKER_RUN_ATTEMPTS} failed: {last_error}", file=sys.stderr)
            if attempt < PICKER_RUN_ATTEMPTS:
                time.sleep(PICKER_RUN_SLEEP_SEC)
        finally:
            if broker is not None and hasattr(broker, "ib") and hasattr(broker.ib, "disconnect"):
                try:
                    broker.ib.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    _write_rank_status(
        picker_paths,
        {
            "status": "failed",
            "ok": False,
            "reason": "retries_exhausted",
            "error": last_error,
            "attempts": PICKER_RUN_ATTEMPTS,
            "at_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
    )
    if not args.no_email:
        try:
            from app.picker.notify import build_crash_email_body, send_picker_email

            send_picker_email(
                "[PICKER] FAILED — retries exhausted",
                build_crash_email_body(error=last_error or "unknown", attempts=PICKER_RUN_ATTEMPTS),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"warn: failure email failed: {exc}", file=sys.stderr)
    return 1


def _picker_client_ids() -> list[int]:
    """Primary picker id + fallbacks (never live-worker 1 / dashboard 9)."""
    primary = int(os.environ.get("PICKER_IB_CLIENT_ID", str(PICKER_CLIENT_ID_DEFAULT)))
    ordered = [primary, *[c for c in PICKER_CLIENT_ID_FALLBACKS if c != primary]]
    # Drop reserved ids if someone misconfigured env.
    return [c for c in ordered if c not in {1, 9}]


def _connect_picker_broker():
    """Connect with retries; rotate client ids on 'already in use' collisions."""
    from app.broker.ibkr import IbkrBroker

    port = int(os.environ.get("IB_PORT", "4002"))
    last_exc: Exception | None = None
    for client_id in _picker_client_ids():
        for attempt in range(1, PICKER_CONNECT_ATTEMPTS + 1):
            # Always overwrite — systemd EnvironmentFile often sets IB_CLIENT_ID=1.
            os.environ["IB_CLIENT_ID"] = str(client_id)
            try:
                broker = IbkrBroker(dry_run=True, port=port)
                return broker, client_id, port
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                print(
                    f"picker IB connect failed client_id={client_id} "
                    f"attempt={attempt}/{PICKER_CONNECT_ATTEMPTS}: {exc}",
                    file=sys.stderr,
                )
                busy = "already in use" in msg or "client id" in msg or "clientid" in msg
                if busy:
                    break  # try next client id
                if attempt < PICKER_CONNECT_ATTEMPTS:
                    time.sleep(PICKER_CONNECT_SLEEP_SEC)
    raise RuntimeError(f"picker IB connect failed after retries: {last_exc}") from last_exc


def _write_rank_status(picker_paths: PickerPaths, status: dict) -> None:
    try:
        picker_paths.state_dir.mkdir(parents=True, exist_ok=True)
        picker_paths.last_rank_status_path.write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"warn: could not write last_rank_status: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
