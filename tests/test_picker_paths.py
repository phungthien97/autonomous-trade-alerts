from app.paths import PickerPaths, ROOT
from app.picker import PickerPaths as ExportedPickerPaths


def test_picker_paths_default_under_repo() -> None:
    paths = PickerPaths()
    assert paths.state_dir == ROOT / "state_picker"
    assert paths.sp500_cache_path == ROOT / "state_picker" / "sp500_cache.json"
    assert paths.pending_selection_path.name == "pending_selection.json"
    assert paths.active_selection_path.name == "active_selection.json"
    assert paths.ranking_runs_dir == ROOT / "state_picker" / "ranking_runs"


def test_picker_paths_respect_project_root(tmp_path) -> None:
    paths = PickerPaths(project_root=tmp_path)
    assert paths.state_dir == tmp_path / "state_picker"
    assert paths.sp500_cache_path == tmp_path / "state_picker" / "sp500_cache.json"
    assert paths.pending_selection_path == tmp_path / "state_picker" / "pending_selection.json"
    assert paths.active_selection_path == tmp_path / "state_picker" / "active_selection.json"
    assert paths.ranking_runs_dir == tmp_path / "state_picker" / "ranking_runs"


def test_picker_paths_exported_from_package() -> None:
    assert ExportedPickerPaths is PickerPaths
