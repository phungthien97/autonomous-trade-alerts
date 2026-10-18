"""Pure on-disk status loaders for the remote Streamlit dashboard (§13)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _positions_from_assets(assets: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, row in (assets or {}).items():
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "symbol": str(symbol),
                "shares": float(row.get("shares", 0.0) or 0.0),
                "cash": float(row.get("cash", 0.0) or 0.0),
                "last_price": row.get("last_price"),
                "peak": row.get("peak"),
                "trough": row.get("trough"),
                "initial_cash": row.get("initial_cash"),
                "last_action": row.get("last_action"),
            }
        )
    rows.sort(key=lambda r: r["symbol"])
    return rows


def load_live_status(state_live_dir: Path) -> dict[str, Any]:
    """Build live dashboard snapshot from ``state_live/`` files."""
    root = Path(state_live_dir)
    config = _read_json(root / "config.json") or {}
    state = _read_json(root / "state.json") or {}
    risk = _read_json(root / "risk.json") or {}
    last_cycle = _read_json(root / "last_cycle.json")

    trading_enabled = bool(config.get("trading_enabled", True))
    if "trading_enabled" in risk:
        trading_enabled = bool(risk.get("trading_enabled"))

    return {
        "mode": str(config.get("mode", "live_dry_run")),
        "symbols": list(config.get("symbols") or []),
        "trading_enabled": trading_enabled,
        "incident": risk.get("open_incident"),
        "cash_usd": state.get("cash_usd"),
        "positions": _positions_from_assets(state.get("assets") or {}),
        "last_cycle": last_cycle,
        "total_cash": config.get("total_cash"),
    }


def load_paper_status(state_dir: Path) -> dict[str, Any]:
    """Build paper V1/V2 snapshot from a ``state/`` or ``state_v2/`` dir."""
    root = Path(state_dir)
    config = _read_json(root / "config.json") or {}
    state = _read_json(root / "state.json") or {}
    assets = state.get("assets") or {}
    if not assets and isinstance(state.get("symbol"), str):
        # Legacy single-symbol shape
        sym = str(state["symbol"])
        assets = {sym: state}
    positions = _positions_from_assets(assets if isinstance(assets, dict) else {})
    cash = state.get("cash_usd")
    if cash is None:
        cash = state.get("cash")
    # Prefer explicit portfolio_value; else cash + mark-to-market.
    portfolio = state.get("portfolio_value")
    if portfolio is None:
        total = float(cash or 0.0)
        for row in positions:
            shares = float(row.get("shares") or 0.0)
            px = row.get("last_price")
            if shares and isinstance(px, (int, float)):
                total += shares * float(px)
            else:
                total += float(row.get("cash") or 0.0)
        portfolio = total
    return {
        "symbols": list(config.get("symbols") or list(assets.keys())),
        "cash_usd": cash,
        "portfolio_value": portfolio,
        "last_run_at": state.get("last_run_at"),
        "positions": positions,
        "exists": (root / "state.json").is_file() or (root / "config.json").is_file(),
    }


def _latest_ranking_meta(runs_dir: Path) -> dict[str, Any] | None:
    if not runs_dir.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = 0.0
    for path in runs_dir.glob("*.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= newest_mtime:
            newest_mtime = mtime
            newest = path
    if newest is None:
        return None
    raw = _read_json(newest) or {}
    selected = raw.get("selected") or raw.get("symbols") or []
    names: list[str] = []
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict) and item.get("symbol"):
                names.append(str(item["symbol"]))
    return {
        "run_id": str(raw.get("run_id") or newest.stem),
        "path": str(newest.name),
        "aborted": bool(raw.get("aborted", False)),
        "dry_run": bool(raw.get("dry_run", False)),
        "selected": names,
        "ok": raw.get("ok"),
    }


def load_picker_status(state_picker_dir: Path) -> dict[str, Any]:
    """Active / pending / latest ranking meta from ``state_picker/``."""
    root = Path(state_picker_dir)
    active = _read_json(root / "active_selection.json")
    pending = _read_json(root / "pending_selection.json")
    active_symbols: list[dict[str, Any]] = []
    if active and isinstance(active.get("symbols"), list):
        for row in active["symbols"]:
            if not isinstance(row, dict):
                continue
            active_symbols.append(
                {
                    "symbol": str(row.get("symbol", "")),
                    "buy_rise": row.get("buy_rise"),
                    "sell_drop": row.get("sell_drop"),
                    "exit_only": bool(row.get("exit_only", False)),
                    "awaiting_first_buy": bool(row.get("awaiting_first_buy", False)),
                }
            )
    pending_symbols: list[str] = []
    apply_after = None
    if pending:
        apply_after = pending.get("apply_after")
        for row in pending.get("symbols") or []:
            if isinstance(row, dict) and row.get("symbol"):
                pending_symbols.append(str(row["symbol"]))
            elif isinstance(row, str):
                pending_symbols.append(row)
    return {
        "active": active_symbols,
        "active_run_id": (active or {}).get("run_id") if active else None,
        "active_applied_at": (active or {}).get("applied_at") if active else None,
        "pending_present": pending is not None,
        "pending_symbols": pending_symbols,
        "pending_apply_after": apply_after,
        "latest_run": _latest_ranking_meta(root / "ranking_runs"),
    }


def last_cycle_age_minutes(last_cycle: dict[str, Any] | None, *, now: datetime | None = None) -> float | None:
    if not last_cycle:
        return None
    raw = last_cycle.get("at_utc") or last_cycle.get("at")
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    now_utc = now or datetime.now(timezone.utc)
    return max(0.0, (now_utc - at).total_seconds() / 60.0)
