from pathlib import Path

from app.picker.active import (
    ActiveSelection,
    ActiveSymbol,
    clear_awaiting_first_buy,
    clear_exit_only_if_flat,
    load_active,
    save_active,
)


def test_active_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "active_selection.json"
    data = ActiveSelection(
        applied_at="2026-10-13T13:35:00+00:00",
        run_id="run1",
        symbols=[
            ActiveSymbol(
                symbol="MSFT",
                buy_rise=0.02,
                sell_drop=0.03,
                exit_only=False,
                awaiting_first_buy=True,
                joined_at="2026-10-13T13:35:00+00:00",
            )
        ],
    )
    save_active(path, data)
    loaded = load_active(path)
    assert loaded is not None
    assert loaded.symbols[0].symbol == "MSFT"
    assert loaded.symbols[0].awaiting_first_buy is True


def test_clear_flags() -> None:
    active = ActiveSelection(
        applied_at="t",
        run_id="r",
        symbols=[
            ActiveSymbol("A", 0.02, 0.03, exit_only=True),
            ActiveSymbol("B", 0.02, 0.03, awaiting_first_buy=True),
        ],
    )
    assert clear_exit_only_if_flat(active, "A", shares=1.0) is False
    assert clear_exit_only_if_flat(active, "A", shares=0.0) is True
    assert active.get("A").exit_only is False  # type: ignore[union-attr]
    assert clear_awaiting_first_buy(active, "B") is True
    assert active.get("B").awaiting_first_buy is False  # type: ignore[union-attr]
