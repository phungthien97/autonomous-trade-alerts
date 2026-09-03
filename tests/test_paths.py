from __future__ import annotations

import pytest

from app.paths import ROOT, StatePaths, get_state_dir


def test_paths_v1_points_to_state() -> None:
    assert get_state_dir("v1") == ROOT / "state"


def test_paths_v2_points_to_state_v2() -> None:
    assert get_state_dir("v2") == ROOT / "state_v2"


def test_paths_unknown_version_raises() -> None:
    with pytest.raises(ValueError, match="Unknown version"):
        get_state_dir("v3")


def test_state_paths_resolves_files(tmp_path) -> None:
    paths = StatePaths(version="v2", project_root=tmp_path)
    assert paths.state_dir == tmp_path / "state_v2"
    assert paths.config_path == tmp_path / "state_v2" / "config.json"
    assert paths.trades_path == tmp_path / "state_v2" / "trades.csv"
    assert paths.equity_path == tmp_path / "state_v2" / "equity.csv"
    assert paths.params_path == tmp_path / "state_v2" / "params_history.csv"
