from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERSION_DIRS = {
    "v1": "state",
    "v2": "state_v2",
}


def get_state_dir(version: str = "v1", project_root: Path | None = None) -> Path:
    if version not in VERSION_DIRS:
        raise ValueError(f"Unknown version {version!r}; expected one of {sorted(VERSION_DIRS)}")
    base = project_root if project_root is not None else ROOT
    return base / VERSION_DIRS[version]


@dataclass(frozen=True)
class StatePaths:
    version: str = "v1"
    project_root: Path | None = None

    @property
    def state_dir(self) -> Path:
        return get_state_dir(self.version, self.project_root)

    @property
    def config_path(self) -> Path:
        return self.state_dir / "config.json"

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def trades_path(self) -> Path:
        return self.state_dir / "trades.csv"

    @property
    def equity_path(self) -> Path:
        return self.state_dir / "equity.csv"

    @property
    def params_path(self) -> Path:
        return self.state_dir / "params_history.csv"

    @property
    def meta_history_path(self) -> Path:
        return self.state_dir / "meta_history.csv"
