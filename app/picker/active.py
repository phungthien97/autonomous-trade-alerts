"""Active selection store with soft-rotate metadata."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ActiveSymbol:
    symbol: str
    buy_rise: float
    sell_drop: float
    exit_only: bool = False
    awaiting_first_buy: bool = False
    joined_at: str | None = None


@dataclass
class ActiveSelection:
    applied_at: str
    run_id: str
    symbols: list[ActiveSymbol] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied_at": self.applied_at,
            "run_id": self.run_id,
            "symbols": [asdict(s) for s in self.symbols],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ActiveSelection:
        symbols = [
            ActiveSymbol(
                symbol=str(row["symbol"]),
                buy_rise=float(row["buy_rise"]),
                sell_drop=float(row["sell_drop"]),
                exit_only=bool(row.get("exit_only", False)),
                awaiting_first_buy=bool(row.get("awaiting_first_buy", False)),
                joined_at=row.get("joined_at"),
            )
            for row in raw.get("symbols", [])
        ]
        return cls(
            applied_at=str(raw.get("applied_at", "")),
            run_id=str(raw.get("run_id", "")),
            symbols=symbols,
        )

    def get(self, symbol: str) -> ActiveSymbol | None:
        for row in self.symbols:
            if row.symbol == symbol:
                return row
        return None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def save_active(path: Path, data: ActiveSelection) -> None:
    _atomic_write(path, data.to_dict())


def load_active(path: Path) -> ActiveSelection | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return ActiveSelection.from_dict(raw)


def clear_exit_only_if_flat(active: ActiveSelection, symbol: str, shares: float) -> bool:
    """Clear exit_only when position is flat. Returns True if mutated."""
    row = active.get(symbol)
    if row is None or not row.exit_only:
        return False
    if float(shares) > 0:
        return False
    row.exit_only = False
    return True


def clear_awaiting_first_buy(active: ActiveSelection, symbol: str) -> bool:
    """Clear awaiting_first_buy after first buy fill. Returns True if mutated."""
    row = active.get(symbol)
    if row is None or not row.awaiting_first_buy:
        return False
    row.awaiting_first_buy = False
    return True
