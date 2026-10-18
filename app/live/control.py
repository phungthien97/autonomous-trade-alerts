"""Dashboard controls that only touch state_live files. No secrets."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.live.config import load_live_config, save_live_config
from app.paths import LivePaths
from app.risk.escalate import RiskController


def _paths(paths: LivePaths | None) -> LivePaths:
    return paths or LivePaths()


def live_status(paths: LivePaths | None = None) -> dict:
    chosen = _paths(paths)
    status = {
        "mode": "live_dry_run",
        "symbols": [],
        "trading_enabled": False,
        "incident": None,
        "assets": {},
    }
    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        status["mode"] = config.mode.value
        status["symbols"] = list(config.symbols)
        status["trading_enabled"] = config.trading_enabled
    if chosen.risk_path.exists():
        raw = json.loads(chosen.risk_path.read_text(encoding="utf-8"))
        status["trading_enabled"] = bool(raw.get("trading_enabled", status["trading_enabled"]))
        status["incident"] = raw.get("open_incident")
    if chosen.state_path.exists():
        state = json.loads(chosen.state_path.read_text(encoding="utf-8"))
        status["assets"] = state.get("assets", {})
    return status


def disable_trading(paths: LivePaths | None = None) -> None:
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    RiskController(chosen.risk_path).disable()
    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        config.trading_enabled = False
        save_live_config(chosen.config_path, config)


def enable_trading(paths: LivePaths | None = None) -> None:
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    RiskController(chosen.risk_path).enable()
    if chosen.config_path.exists():
        config = load_live_config(chosen.config_path)
        config.trading_enabled = True
        save_live_config(chosen.config_path, config)


def ack_risk(paths: LivePaths | None = None, now: datetime | None = None) -> None:
    chosen = _paths(paths)
    chosen.state_dir.mkdir(parents=True, exist_ok=True)
    RiskController(chosen.risk_path).ack(now or datetime.now(timezone.utc))
