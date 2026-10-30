"""Prune exit-only symbols out of live config once flat."""

from __future__ import annotations

import json
from pathlib import Path

from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.picker.apply_live import remove_symbol_from_live_book, remove_symbol_from_live_config


def test_remove_symbol_from_live_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    save_live_config(
        cfg_path,
        LiveConfig(
            symbols=["P", "FICO"],
            assets=[SymbolParams("P"), SymbolParams("FICO")],
        ),
    )
    updated = remove_symbol_from_live_config(cfg_path, "P")
    assert updated is not None
    assert updated.symbols == ["FICO"]
    assert [a.symbol for a in updated.assets] == ["FICO"]


def test_remove_symbol_from_live_book_drops_flat_state(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    save_live_config(
        cfg_path,
        LiveConfig(symbols=["HUM", "VLO"], assets=[SymbolParams("HUM"), SymbolParams("VLO")]),
    )
    state_path.write_text(
        json.dumps(
            {
                "assets": {
                    "HUM": {"shares": 0.0, "cash": 1.0},
                    "VLO": {"shares": 10.0, "cash": 0.0},
                }
            }
        ),
        encoding="utf-8",
    )
    assert remove_symbol_from_live_book(cfg_path, state_path, "HUM") is True
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert "HUM" not in raw["assets"]
    assert "VLO" in raw["assets"]
