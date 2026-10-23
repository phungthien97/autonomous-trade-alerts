"""Alert-first risk incidents that auto-stop trading after 2 hours without ack."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


@dataclass
class OpenIncident:
    id: str
    kind: str
    alerted_at: str
    acked_at: str | None = None
    stopped: bool = False


class RiskController:
    def __init__(self, path: Path, escalate_after: timedelta = timedelta(hours=2)) -> None:
        self.path = Path(path)
        self.escalate_after = escalate_after
        if not self.path.exists():
            self._write(True, None)

    def _read(self) -> tuple[bool, OpenIncident | None]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        enabled = bool(data.get("trading_enabled", True))
        raw = data.get("open_incident")
        if not raw:
            return enabled, None
        return enabled, OpenIncident(
            id=raw["id"],
            kind=raw["kind"],
            alerted_at=raw["alerted_at"],
            acked_at=raw.get("acked_at"),
            stopped=bool(raw.get("stopped", False)),
        )

    def _write(self, trading_enabled: bool, incident: OpenIncident | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trading_enabled": trading_enabled,
            "open_incident": None
            if incident is None
            else {
                "id": incident.id,
                "kind": incident.kind,
                "alerted_at": incident.alerted_at,
                "acked_at": incident.acked_at,
                "stopped": incident.stopped,
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def trading_enabled(self) -> bool:
        enabled, _ = self._read()
        return enabled

    def trigger(self, kind: str, now: datetime) -> tuple[OpenIncident, bool]:
        """Open a risk incident if none is active.

        Returns ``(incident, created)`` — ``created`` is True only on the first
        open so callers can email once instead of every worker cycle.
        """
        enabled, incident = self._read()
        if incident is not None and incident.acked_at is None and not incident.stopped:
            return incident, False
        incident = OpenIncident(id=str(uuid.uuid4()), kind=kind, alerted_at=_iso(now))
        self._write(enabled, incident)
        return incident, True

    def ack(self, now: datetime) -> None:
        enabled, incident = self._read()
        if incident is None:
            return
        incident.acked_at = _iso(now)
        self._write(enabled, None)

    def tick(self, now: datetime) -> bool:
        """Return True if this tick newly disabled trading."""
        enabled, incident = self._read()
        if incident is None or incident.acked_at is not None or incident.stopped:
            return False
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        alerted = _parse(incident.alerted_at)
        if now - alerted >= self.escalate_after:
            incident.stopped = True
            self._write(False, incident)
            return True
        return False

    def disable(self) -> None:
        _, incident = self._read()
        self._write(False, incident)

    def enable(self) -> None:
        self._write(True, None)
