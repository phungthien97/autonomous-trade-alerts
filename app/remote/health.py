"""Health strip model for the remote dashboard (§13)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.remote.status import last_cycle_age_minutes


def _parse_health_log_tail(path: Path, max_lines: int = 40) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-max_lines:]):
        if "status=" not in line:
            continue
        # gateway-health.sh style: ... status=OK port4002=1 api_ok=1 ...
        fields: dict[str, str] = {}
        for part in line.split():
            if "=" in part:
                k, _, v = part.partition("=")
                fields[k] = v
        if "status" in fields:
            return fields
    return None


def build_health_strip(
    *,
    live_status: dict[str, Any],
    gateway_health_log: Path | None = None,
    worker_fresh_minutes: float = 15.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return labels/booleans for the phone health strip."""
    last_cycle = live_status.get("last_cycle") if isinstance(live_status.get("last_cycle"), dict) else None
    stale = last_cycle_age_minutes(last_cycle, now=now)
    worker_fresh = stale is not None and stale <= worker_fresh_minutes

    health_fields = _parse_health_log_tail(gateway_health_log) if gateway_health_log else None
    gateway_ok: bool | None = None
    api_ok: bool | None = None
    if health_fields:
        gateway_ok = health_fields.get("status") == "OK"
        if "api_ok" in health_fields:
            api_ok = health_fields["api_ok"] == "1"

    mode = str(live_status.get("mode", "unknown"))
    trading_on = bool(live_status.get("trading_enabled"))
    incident = live_status.get("incident")
    risk_open = incident is not None and incident != {}

    rth_ok = None
    price_source = None
    if last_cycle:
        rth_ok = last_cycle.get("rth_ok")
        price_source = last_cycle.get("price_source")

    return {
        "worker_fresh": worker_fresh,
        "stale_minutes": round(stale, 1) if stale is not None else None,
        "mode": mode,
        "trading_on": trading_on,
        "risk_open": bool(risk_open),
        "incident": incident,
        "rth_ok": rth_ok,
        "price_source": price_source,
        "gateway_ok": gateway_ok,
        "api_ok": api_ok,
        "gateway_health_raw": health_fields,
    }
