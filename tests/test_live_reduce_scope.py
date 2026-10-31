"""Reduce must never sell unmanaged IBKR longs; preview ≡ execute universe."""

from __future__ import annotations

import json
from pathlib import Path

from app.live.budget import plan_reduce_to_budget
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.control import bot_book_symbols, preview_reduce_to_budget, scoped_bot_positions
from app.paths import LivePaths, PickerPaths
from app.picker.active import ActiveSelection, ActiveSymbol, save_active


def _seed_book(tmp_path: Path) -> LivePaths:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(
            symbols=["P", "FICO"],
            total_cash=1000.0,
            trading_budget_usd=200.0,
            assets=[SymbolParams(symbol="P"), SymbolParams(symbol="FICO")],
            trading_enabled=True,
        ),
    )
    picker = PickerPaths(project_root=tmp_path)
    save_active(
        picker.active_selection_path,
        ActiveSelection(
            applied_at="t",
            run_id="r",
            symbols=[
                ActiveSymbol("P", 0.01, 0.05),
                ActiveSymbol("FICO", 0.01, 0.05),
                ActiveSymbol("AMGN", 0.01, 0.05, exit_only=True),
            ],
        ),
    )
    paths.state_path.write_text(json.dumps({"assets": {}}), encoding="utf-8")
    return paths


def test_bot_book_includes_exit_only_not_orphans(tmp_path: Path) -> None:
    paths = _seed_book(tmp_path)
    book = set(bot_book_symbols(paths))
    assert book == {"P", "FICO", "AMGN"}


def test_scoped_positions_drop_unmanaged_long(tmp_path: Path) -> None:
    paths = _seed_book(tmp_path)
    brokerish = {"P": 10.0, "FICO": 1.0, "TSLA": 50.0, "AMGN": 2.0}
    scoped = scoped_bot_positions(paths, brokerish)
    assert set(scoped) == {"P", "FICO", "AMGN"}
    assert "TSLA" not in scoped


def test_preview_reduce_with_paths_ignores_orphan(tmp_path: Path) -> None:
    paths = _seed_book(tmp_path)
    positions = {"P": 100.0, "TSLA": 100.0}
    prices = {"P": 1.0, "TSLA": 1.0}  # invested bot=100, orphan=100, total broker=200
    # Target 50 → should only sell from P (bot), not TSLA.
    plan = preview_reduce_to_budget(
        positions=positions, prices=prices, budget_usd=50.0, paths=paths
    )
    assert {row["symbol"] for row in plan} == {"P"}
    raw = plan_reduce_to_budget(positions, prices, budget_usd=50.0)
    assert {s.symbol for s in raw} == {"P", "TSLA"}


def test_empty_bot_book_scopes_to_nothing(tmp_path: Path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    assert bot_book_symbols(paths) == []
    assert scoped_bot_positions(paths, {"AAPL": 10.0}) == {}
