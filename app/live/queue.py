"""JSON-backed queue of orders waiting for the next regular session."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PendingIntent:
    symbol: str
    side: str
    bar_ts: str
    created_at: str
    reason: str


class PendingIntentStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> list[PendingIntent]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [PendingIntent(**row) for row in raw.get("intents", [])]

    def _save(self, intents: list[PendingIntent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"intents": [asdict(item) for item in intents]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def enqueue(self, intent: PendingIntent) -> bool:
        intents = self._load()
        key = (intent.symbol, intent.bar_ts, intent.side)
        if any((row.symbol, row.bar_ts, row.side) == key for row in intents):
            return False
        intents.append(intent)
        self._save(intents)
        return True

    def list_pending(self) -> list[PendingIntent]:
        return self._load()

    def pop_symbol(self, symbol: str) -> list[PendingIntent]:
        intents = self._load()
        kept = [row for row in intents if row.symbol != symbol]
        popped = [row for row in intents if row.symbol == symbol]
        self._save(kept)
        return popped

    def clear(self) -> None:
        self._save([])
