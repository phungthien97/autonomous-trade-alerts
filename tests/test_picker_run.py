from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.paths import PickerPaths
from app.picker.bars import FixtureBarProvider
from app.picker.pending import load_pending
from app.picker.run import run_ranking

ET = ZoneInfo("America/New_York")


def _dip_rally_series(start: date, days: int, base: float = 100.0):
    rows = []
    px = base
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        if i < days // 2:
            px *= 0.985
        else:
            px *= 1.015
        rows.append((datetime(d.year, d.month, d.day, 10, 30, tzinfo=ET), px))
    return rows


def test_run_ranking_writes_pending(tmp_path: Path, monkeypatch) -> None:
    picker = PickerPaths(project_root=tmp_path)
    start = date(2026, 9, 1)
    series = {
        "GOOD": _dip_rally_series(start, 50, 100.0),
        "MEH": _dip_rally_series(start, 50, 50.0),
    }
    provider = FixtureBarProvider(series=series)
    sent: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "app.picker.run.send_picker_email",
        lambda subject, body: sent.append((subject, body)) or True,
    )

    result = run_ranking(
        as_of=date(2026, 10, 11),
        sp500_loader=lambda: ["GOOD", "MEH"],
        bar_provider=provider,
        picker_paths=picker,
        active_symbols=["OLD"],
        send_email=True,
        dry_run=False,
    )
    assert result.ok is True
    assert result.pending_written is True
    pending = load_pending(picker.pending_selection_path)
    assert pending is not None and pending.status == "pending"
    assert len(pending.symbols) >= 1
    assert "GOOD" in result.email_body or pending.symbols[0].symbol in result.email_body
    assert sent and "PICKER" in sent[0][0]


def test_run_ranking_abort_keeps_pending(tmp_path: Path) -> None:
    picker = PickerPaths(project_root=tmp_path)
    start = date(2026, 9, 1)
    symbols = [f"S{i}" for i in range(10)]
    series = {s: _dip_rally_series(start, 50, 100 + i) for i, s in enumerate(symbols)}
    provider = FixtureBarProvider(series=series, fail_symbols=set(symbols[:4]))

    # Seed an existing pending that must remain.
    from app.picker.pending import PendingSelection, PendingSymbol, save_pending

    save_pending(
        picker.pending_selection_path,
        PendingSelection(
            run_id="keep",
            computed_at="t",
            apply_after="t2",
            symbols=[PendingSymbol("KEEP", 0.02, 0.03, 0.1, 0.2, 0.1)],
            status="pending",
        ),
    )

    result = run_ranking(
        as_of=date(2026, 10, 11),
        sp500_loader=lambda: symbols,
        bar_provider=provider,
        picker_paths=picker,
        active_symbols=["KEEP"],
        send_email=False,
        dry_run=False,
    )
    assert result.aborted is True
    assert result.pending_written is False
    pending = load_pending(picker.pending_selection_path)
    assert pending is not None and pending.symbols[0].symbol == "KEEP"
    assert "ABORT" in result.email_subject


def test_run_ranking_dry_run_skips_pending(tmp_path: Path) -> None:
    picker = PickerPaths(project_root=tmp_path)
    start = date(2026, 9, 1)
    provider = FixtureBarProvider(series={"AAPL": _dip_rally_series(start, 50)})
    result = run_ranking(
        as_of=date(2026, 10, 11),
        sp500_loader=lambda: ["AAPL"],
        bar_provider=provider,
        picker_paths=picker,
        dry_run=True,
    )
    assert result.ok is True
    assert result.pending_written is False
    assert load_pending(picker.pending_selection_path) is None
    assert "DRY RUN" in result.email_subject
