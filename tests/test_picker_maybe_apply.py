from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.live.config import LiveConfig, save_live_config
from app.paths import LivePaths, PickerPaths, StatePaths
from app.picker.active import ActiveSelection, ActiveSymbol, save_active
from app.picker.apply import maybe_apply_pending
from app.picker.pending import PendingSelection, PendingSymbol, load_pending, save_pending


def _seed(tmp_path: Path) -> tuple[PickerPaths, LivePaths, StatePaths, StatePaths]:
    picker = PickerPaths(project_root=tmp_path)
    live = LivePaths(project_root=tmp_path)
    v1 = StatePaths(version="v1", project_root=tmp_path)
    v2 = StatePaths(version="v2", project_root=tmp_path)
    save_live_config(live.config_path, LiveConfig())
    for paths in (v1, v2):
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            '{"initial_cash": 1000.0, "assets": []}', encoding="utf-8"
        )
        paths.state_path.write_text('{"assets": {}}', encoding="utf-8")
    return picker, live, v1, v2


def test_maybe_apply_on_monday_rth(tmp_path: Path) -> None:
    picker, live, v1, v2 = _seed(tmp_path)
    apply_after = datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc)  # Mon 09:30 ET
    save_pending(
        picker.pending_selection_path,
        PendingSelection(
            run_id="r",
            computed_at=(apply_after - timedelta(days=2)).isoformat(),
            apply_after=apply_after.isoformat(),
            symbols=[PendingSymbol("AAPL", 0.02, 0.03, 0.1, 0.2, 0.05)],
            status="pending",
        ),
    )
    now = apply_after + timedelta(minutes=5)
    result = maybe_apply_pending(picker, live, v1, v2, now, rth_ok=True)
    assert result.applied is True
    assert load_pending(picker.pending_selection_path).status == "applied"  # type: ignore[union-attr]


def test_maybe_apply_before_open_noop(tmp_path: Path) -> None:
    picker, live, v1, v2 = _seed(tmp_path)
    apply_after = datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc)
    save_pending(
        picker.pending_selection_path,
        PendingSelection(
            run_id="r",
            computed_at=apply_after.isoformat(),
            apply_after=apply_after.isoformat(),
            symbols=[PendingSymbol("AAPL", 0.02, 0.03, 0.1, 0.2, 0.05)],
            status="pending",
        ),
    )
    result = maybe_apply_pending(
        picker, live, v1, v2, apply_after - timedelta(hours=1), rth_ok=True
    )
    assert result.applied is False
    assert result.reason == "before_apply_after"


def test_maybe_apply_stale_flag(tmp_path: Path) -> None:
    picker, live, v1, v2 = _seed(tmp_path)
    apply_after = datetime(2026, 10, 20, 13, 30, tzinfo=timezone.utc)
    save_pending(
        picker.pending_selection_path,
        PendingSelection(
            run_id="old",
            computed_at=(apply_after - timedelta(days=5)).isoformat(),
            apply_after=apply_after.isoformat(),
            symbols=[],
            status="pending",
        ),
    )
    result = maybe_apply_pending(
        picker, live, v1, v2, apply_after - timedelta(days=1), rth_ok=True
    )
    assert result.applied is False
    assert result.reason == "stale_pending_before_apply"
