from datetime import datetime, timezone
from pathlib import Path

from app.live.config import LiveConfig, save_live_config
from app.paths import LivePaths, PickerPaths, StatePaths
from app.picker.active import ActiveSelection, ActiveSymbol, load_active, save_active
from app.picker.apply import apply_pending_selection
from app.picker.pending import PendingSelection, PendingSymbol, load_pending, save_pending


def _paths(root: Path) -> tuple[PickerPaths, LivePaths, StatePaths, StatePaths]:
    return (
        PickerPaths(project_root=root),
        LivePaths(project_root=root),
        StatePaths(version="v1", project_root=root),
        StatePaths(version="v2", project_root=root),
    )


def test_apply_pending_happy_path_and_idempotent(tmp_path: Path) -> None:
    picker, live, v1, v2 = _paths(tmp_path)
    save_live_config(live.config_path, LiveConfig())
    for paths in (v1, v2):
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            '{"initial_cash": 1000.0, "assets": []}',
            encoding="utf-8",
        )
        paths.state_path.write_text('{"assets": {}}', encoding="utf-8")

    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="old",
            run_id="old",
            symbols=[ActiveSymbol("MSFT", 0.02, 0.03)],
        ),
    )
    save_pending(
        picker.pending_selection_path,
        PendingSelection(
            run_id="run2",
            computed_at="2026-10-11T00:00:00+00:00",
            apply_after="2026-10-13T13:30:00+00:00",
            symbols=[PendingSymbol("AAPL", 0.01, 0.02, 0.1, 0.2, 0.05)],
            status="pending",
        ),
    )

    result = apply_pending_selection(
        picker, live, v1, v2, now=datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
    )
    assert result.applied is True
    active = load_active(picker.active_selection_path)
    assert active is not None
    symbols = {s.symbol: s for s in active.symbols}
    assert symbols["AAPL"].awaiting_first_buy is True
    assert symbols["MSFT"].exit_only is True
    assert load_pending(picker.pending_selection_path).status == "applied"  # type: ignore[union-attr]

    again = apply_pending_selection(picker, live, v1, v2)
    assert again.applied is False
    assert again.reason == "already_applied"


def test_apply_missing_pending_noop(tmp_path: Path) -> None:
    picker, live, v1, v2 = _paths(tmp_path)
    result = apply_pending_selection(picker, live, v1, v2)
    assert result.applied is False
    assert result.reason == "no_pending"


def test_apply_empty_pending_marks_prior_exit_only(tmp_path: Path) -> None:
    picker, live, v1, v2 = _paths(tmp_path)
    save_live_config(live.config_path, LiveConfig())
    for paths in (v1, v2):
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            '{"initial_cash": 1000.0, "assets": [{"symbol": "AAPL", "buy_rise_pct": 1, "sell_drop_pct": 2, "x_days": 20, "reopt_days": 5, "enabled": true}]}',
            encoding="utf-8",
        )
        paths.state_path.write_text(
            '{"assets": {"AAPL": {"cash": 0, "shares": 1, "initial_cash": 1000}}}',
            encoding="utf-8",
        )
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="old",
            run_id="old",
            symbols=[ActiveSymbol("AAPL", 0.01, 0.02)],
        ),
    )
    save_pending(
        picker.pending_selection_path,
        PendingSelection(
            run_id="cash",
            computed_at="t",
            apply_after="t2",
            symbols=[],
            status="pending",
        ),
    )
    result = apply_pending_selection(picker, live, v1, v2)
    assert result.applied is True
    active = load_active(picker.active_selection_path)
    assert [s.symbol for s in active.symbols] == ["AAPL"]  # type: ignore[union-attr]
    assert active.symbols[0].exit_only is True  # type: ignore[union-attr]
