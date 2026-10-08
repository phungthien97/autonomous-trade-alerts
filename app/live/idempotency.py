"""File-backed idempotency keys for one order per symbol+bar+side."""

from __future__ import annotations

import json
from pathlib import Path


def intent_key(symbol: str, bar_ts_iso: str, side: str) -> str:
    return f"{symbol}|{bar_ts_iso}|{side}"


class IdempotencyStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(data.get("keys", {}))

    def _write(self, keys: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"keys": keys}, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    def already_done(self, key: str) -> bool:
        return key in self._read()

    def mark_done(self, key: str, meta: dict) -> None:
        keys = self._read()
        keys[key] = dict(meta)
        self._write(keys)

    def list_keys(self) -> list[str]:
        return sorted(self._read().keys())
