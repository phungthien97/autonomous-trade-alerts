from pathlib import Path

from app.picker.pending import (
    PendingSelection,
    PendingSymbol,
    load_pending,
    mark_applied,
    save_pending,
)


def test_pending_round_trip_and_mark_applied(tmp_path: Path) -> None:
    path = tmp_path / "pending_selection.json"
    data = PendingSelection(
        run_id="run1",
        computed_at="2026-10-11T04:00:00+00:00",
        apply_after="2026-10-13T13:30:00+00:00",
        symbols=[
            PendingSymbol(
                symbol="AAPL",
                buy_rise=0.02,
                sell_drop=0.03,
                edge=0.05,
                strategy_return=0.1,
                bh_return=0.05,
            )
        ],
        status="pending",
    )
    save_pending(path, data)
    loaded = load_pending(path)
    assert loaded is not None
    assert loaded.run_id == "run1"
    assert loaded.symbols[0].symbol == "AAPL"
    assert loaded.status == "pending"

    marked = mark_applied(path)
    assert marked is not None and marked.status == "applied"
    assert load_pending(path).status == "applied"  # type: ignore[union-attr]


def test_load_pending_missing_file(tmp_path: Path) -> None:
    assert load_pending(tmp_path / "missing.json") is None
