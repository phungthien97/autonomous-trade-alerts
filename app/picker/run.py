"""Weekend ranking orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from app.paths import PickerPaths
from app.picker.bars import HourlyBarProvider, fetch_universe_bars
from app.picker.notify import (
    build_failure_email_body,
    build_success_email_body,
    build_success_email_subject,
    send_picker_email,
)
from app.picker.pending import PendingSelection, PendingSymbol, save_pending
from app.picker.rank import SelectedSymbol, select_symbols
from app.picker.rank_symbol import rank_one_symbol
from app.picker.sp500 import Sp500Constituent
from app.picker.windows import ranking_windows

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class RankingRunResult:
    ok: bool
    aborted: bool
    dry_run: bool
    run_id: str
    selected: list[SelectedSymbol]
    report_path: str | None
    email_subject: str
    email_body: str
    pending_written: bool


def _as_of_date(as_of: date | datetime) -> date:
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            raise ValueError("as_of datetime must be timezone-aware")
        return as_of.astimezone(ET).date()
    return as_of


def next_monday_rth_open_utc(as_of: date | datetime) -> datetime:
    """First Monday 09:30 America/New_York at or after as_of's calendar week."""
    d = _as_of_date(as_of)
    # weekday: Mon=0 ... Sun=6
    days_ahead = (0 - d.weekday()) % 7
    monday = d + timedelta(days=days_ahead)
    if days_ahead == 0 and isinstance(as_of, datetime):
        # If already Monday after open, still use this Monday (apply_after gate uses >=).
        pass
    local = datetime(monday.year, monday.month, monday.day, 9, 30, tzinfo=ET)
    return local.astimezone(timezone.utc)


def _write_report(picker_paths: PickerPaths, run_id: str, payload: dict) -> str:
    runs = picker_paths.ranking_runs_dir
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{run_id}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return str(path)


def _enrich_selected(
    selected: Sequence[SelectedSymbol],
    profiles: Mapping[str, Sp500Constituent] | None,
) -> list[dict]:
    rows: list[dict] = []
    for s in selected:
        row = asdict(s)
        info = profiles.get(s.symbol) if profiles else None
        if info is not None:
            row["name"] = info.name
            row["sector"] = info.sector
        else:
            row["name"] = ""
            row["sector"] = ""
        rows.append(row)
    return rows


def run_ranking(
    as_of: date | datetime,
    sp500_loader: Callable[[], list[str]],
    bar_provider: HourlyBarProvider,
    picker_paths: PickerPaths,
    active_symbols: Sequence[str] | None = None,
    *,
    send_email: bool = False,
    dry_run: bool = False,
    initial_cash: float = 1000.0,
    book_cash: float | None = None,
    profiles: Mapping[str, Sp500Constituent] | None = None,
) -> RankingRunResult:
    """Score S&P names and write pending selection (unless dry_run / abort).

    ``initial_cash`` is the score/optimize sleeve size. ``book_cash`` is the live
    book used for priority whole-share sleeve allocation (defaults to initial_cash).
    """
    as_of_d = _as_of_date(as_of)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    active = list(active_symbols or [])
    windows = ranking_windows(as_of_d)
    apply_after = next_monday_rth_open_utc(as_of_d)
    opt_label = f"{windows.optimize.start.isoformat()}..{windows.optimize.end.isoformat()}"
    score_label = f"{windows.score.start.isoformat()}..{windows.score.end.isoformat()}"

    symbols = list(sp500_loader())
    fetched = fetch_universe_bars(
        symbols, bar_provider, windows.optimize, windows.score
    )

    if fetched.abort:
        body = build_failure_email_body(
            run_id=run_id,
            as_of=as_of_d.isoformat(),
            skipped=fetched.skipped,
            failure_pct=fetched.failure_pct,
            total_symbols=len(symbols),
        )
        subject = "[PICKER] ABORT — IBKR fetch >30% failed (kept previous list)"
        report = {
            "run_id": run_id,
            "as_of": as_of_d.isoformat(),
            "aborted": True,
            "dry_run": dry_run,
            "failure_pct": fetched.failure_pct,
            "skipped": [{"symbol": s, "reason": r} for s, r in fetched.skipped],
            "selected": [],
        }
        report_path = _write_report(picker_paths, run_id, report)
        if send_email:
            send_picker_email(subject, body)
        return RankingRunResult(
            ok=False,
            aborted=True,
            dry_run=dry_run,
            run_id=run_id,
            selected=[],
            report_path=report_path,
            email_subject=subject,
            email_body=body,
            pending_written=False,
        )

    ranked_rows: list[dict] = []
    last_prices: dict[str, float] = {}
    for symbol, windows_closes in fetched.ok.items():
        result = rank_one_symbol(
            windows_closes.opt_closes,
            windows_closes.score_closes,
            initial_cash=initial_cash,
        )
        row = result.as_dict()
        row["symbol"] = symbol
        ranked_rows.append(row)
        score = list(windows_closes.score_closes or [])
        if score:
            try:
                last_prices[symbol] = float(score[-1])
            except (TypeError, ValueError):
                pass

    allocate_cash = float(book_cash) if book_cash is not None else float(initial_cash)
    selected = select_symbols(
        ranked_rows,
        max_n=5,
        prices=last_prices,
        total_cash=allocate_cash,
    )
    selected_rows = _enrich_selected(selected, profiles)
    body = build_success_email_body(
        run_id=run_id,
        as_of=as_of_d.isoformat(),
        opt_window=opt_label,
        score_window=score_label,
        selected=selected,
        active_symbols=active,
        skipped=fetched.skipped,
        failure_pct=fetched.failure_pct,
        apply_after=apply_after.isoformat(),
        dry_run=dry_run,
        profiles=profiles,
    )
    subject = build_success_email_subject(selected, dry_run=dry_run)
    report = {
        "run_id": run_id,
        "as_of": as_of_d.isoformat(),
        "aborted": False,
        "dry_run": dry_run,
        "opt_window": opt_label,
        "score_window": score_label,
        "apply_after": apply_after.isoformat(),
        "failure_pct": fetched.failure_pct,
        "skipped": [{"symbol": s, "reason": r} for s, r in fetched.skipped],
        "ranked": ranked_rows,
        "selected": selected_rows,
    }
    report_path = _write_report(picker_paths, run_id, report)

    pending_written = False
    if not dry_run:
        pending = PendingSelection(
            run_id=run_id,
            computed_at=datetime.now(timezone.utc).isoformat(),
            apply_after=apply_after.isoformat(),
            symbols=[
                PendingSymbol(
                    symbol=s.symbol,
                    buy_rise=s.buy_rise,
                    sell_drop=s.sell_drop,
                    edge=s.edge,
                    strategy_return=s.strategy_return,
                    bh_return=s.bh_return,
                    name=str(row.get("name") or ""),
                    sector=str(row.get("sector") or ""),
                    allocated_cash=s.allocated_cash,
                    last_price=s.last_price,
                    shares_budget=s.shares_budget,
                )
                for s, row in zip(selected, selected_rows, strict=True)
            ],
            status="pending",
            notes="weekend ranking",
        )
        save_pending(picker_paths.pending_selection_path, pending)
        pending_written = True

    if send_email:
        send_picker_email(subject, body)

    return RankingRunResult(
        ok=True,
        aborted=False,
        dry_run=dry_run,
        run_id=run_id,
        selected=selected,
        report_path=report_path,
        email_subject=subject,
        email_body=body,
        pending_written=pending_written,
    )
