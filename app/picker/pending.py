"""Atomic pending_selection.json store for Monday apply."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

PendingStatus = Literal["pending", "applied", "aborted"]


@dataclass
class PendingSymbol:
    symbol: str
    buy_rise: float
    sell_drop: float
    edge: float
    strategy_return: float
    bh_return: float | None = None
    name: str = ""
    sector: str = ""
    allocated_cash: float | None = None
    last_price: float | None = None
    shares_budget: int | None = None


@dataclass
class PendingSelection:
    run_id: str
    computed_at: str
    apply_after: str
    symbols: list[PendingSymbol] = field(default_factory=list)
    status: PendingStatus = "pending"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "computed_at": self.computed_at,
            "apply_after": self.apply_after,
            "symbols": [asdict(s) for s in self.symbols],
            "status": self.status,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PendingSelection:
        symbols = [
            PendingSymbol(
                symbol=str(row["symbol"]),
                buy_rise=float(row["buy_rise"]),
                sell_drop=float(row["sell_drop"]),
                edge=float(row["edge"]),
                strategy_return=float(row["strategy_return"]),
                bh_return=None if row.get("bh_return") is None else float(row["bh_return"]),
                name=str(row.get("name") or "").strip(),
                sector=str(row.get("sector") or "").strip(),
                allocated_cash=(
                    None if row.get("allocated_cash") is None else float(row["allocated_cash"])
                ),
                last_price=None if row.get("last_price") is None else float(row["last_price"]),
                shares_budget=(
                    None if row.get("shares_budget") is None else int(row["shares_budget"])
                ),
            )
            for row in raw.get("symbols", [])
        ]
        return cls(
            run_id=str(raw["run_id"]),
            computed_at=str(raw["computed_at"]),
            apply_after=str(raw["apply_after"]),
            symbols=symbols,
            status=raw.get("status", "pending"),  # type: ignore[arg-type]
            notes=str(raw.get("notes", "")),
        )


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def save_pending(path: Path, data: PendingSelection) -> None:
    _atomic_write(path, data.to_dict())


def load_pending(path: Path) -> PendingSelection | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return PendingSelection.from_dict(raw)


def mark_applied(path: Path) -> PendingSelection | None:
    pending = load_pending(path)
    if pending is None:
        return None
    pending.status = "applied"
    save_pending(path, pending)
    return pending


def mark_aborted(path: Path, notes: str = "") -> PendingSelection | None:
    pending = load_pending(path)
    if pending is None:
        return None
    pending.status = "aborted"
    if notes:
        pending.notes = notes
    save_pending(path, pending)
    return pending
