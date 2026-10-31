"""Biweekly skip window: weekly timer + age gate ≈ every other Saturday."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.paths import PickerPaths
from app.picker_rank import (
    BIWEEKLY_SKIP_WITHIN_DAYS,
    _picker_client_ids,
    _recent_successful_run,
)


def _write_run(runs: Path, name: str, *, aborted: bool = False) -> Path:
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / name
    path.write_text(json.dumps({"run_id": name, "aborted": aborted}), encoding="utf-8")
    return path


def test_skip_window_blocks_next_saturday_allows_biweekly(tmp_path: Path) -> None:
    runs = tmp_path / "state_picker" / "ranking_runs"
    path = _write_run(runs, "20261018_151053.json")
    # Finished early Monday UTC after a weekend ranking.
    finished = datetime(2026, 10, 19, 0, 14, tzinfo=timezone.utc).timestamp()
    import os

    os.utime(path, (finished, finished))

    paths = PickerPaths(project_root=tmp_path)
    next_week = datetime(2026, 10, 24, 4, 0, tzinfo=timezone.utc).timestamp()
    biweekly = datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc).timestamp()

    assert _recent_successful_run(paths, now_ts=next_week) is not None
    # Previously failed with within_days=13 (age ≈12.2 still skipped).
    assert biweekly - finished > BIWEEKLY_SKIP_WITHIN_DAYS * 86400
    assert _recent_successful_run(paths, now_ts=biweekly) is None


def test_picker_client_ids_never_use_worker_or_dashboard(monkeypatch) -> None:
    monkeypatch.setenv("PICKER_IB_CLIENT_ID", "7")
    monkeypatch.setenv("IB_CLIENT_ID", "1")  # must not win
    ids = _picker_client_ids()
    assert ids[0] == 7
    assert 1 not in ids
    assert 9 not in ids


def test_aborted_run_does_not_block(tmp_path: Path) -> None:
    runs = tmp_path / "state_picker" / "ranking_runs"
    path = _write_run(runs, "20261018_000000.json", aborted=True)
    now = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
    import os

    os.utime(path, (now - 86400, now - 86400))
    assert _recent_successful_run(PickerPaths(project_root=tmp_path), now_ts=now) is None
