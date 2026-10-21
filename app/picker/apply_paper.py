"""Apply picker selection into paper V1/V2 config + state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from app.picker.pending import PendingSymbol


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _default_asset_row(
    symbol: str,
    buy_rise_pct: float,
    sell_drop_pct: float,
    template: dict[str, Any] | None,
    *,
    exit_only: bool = False,
    awaiting_first_buy: bool = False,
) -> dict[str, Any]:
    base = {
        "symbol": symbol,
        "buy_rise_pct": buy_rise_pct,
        "sell_drop_pct": sell_drop_pct,
        "x_days": int((template or {}).get("x_days", 20)),
        "reopt_days": int((template or {}).get("reopt_days", 5)),
        "enabled": True,
        "exit_only": exit_only,
        "awaiting_first_buy": awaiting_first_buy,
    }
    return base


def _default_state_row(initial_cash: float = 1000.0) -> dict[str, Any]:
    return {
        "cash": float(initial_cash),
        "shares": 0.0,
        "peak": None,
        "trough": None,
        "last_price": None,
        "last_action": "HOLD",
        "last_signal_reason": "picker_apply",
        "initial_cash": float(initial_cash),
    }


def apply_to_paper_version(
    config_path: Path,
    state_path: Path,
    symbols: Sequence[PendingSymbol | dict],
    *,
    exit_only_symbols: Sequence[str] | None = None,
    awaiting_first_buy: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Rewrite paper config assets for pending symbols; soft-keep exit_only names."""
    config = _load_json(config_path)
    state = _load_json(state_path)
    prior_assets = {
        str(a.get("symbol", "")).upper(): a
        for a in (config.get("assets") or [])
        if isinstance(a, dict) and a.get("symbol")
    }
    template = next(iter(prior_assets.values()), None) or {
        "x_days": config.get("x_days", 20),
        "reopt_days": config.get("reopt_days", 5),
    }
    initial_cash = float(config.get("initial_cash", 1000.0))
    awaiting = {s.upper() for s in (awaiting_first_buy or [])}
    exit_only = {s.upper() for s in (exit_only_symbols or [])}

    new_assets: list[dict[str, Any]] = []
    pending_syms: list[str] = []
    for row in symbols:
        if isinstance(row, PendingSymbol):
            symbol = row.symbol.upper()
            buy_pct = round(float(row.buy_rise) * 100.0, 6)
            sell_pct = round(float(row.sell_drop) * 100.0, 6)
        else:
            symbol = str(row["symbol"]).upper()
            buy_pct = round(float(row["buy_rise"]) * 100.0, 6)
            sell_pct = round(float(row["sell_drop"]) * 100.0, 6)
        pending_syms.append(symbol)
        new_assets.append(
            _default_asset_row(
                symbol,
                buy_pct,
                sell_pct,
                template,
                exit_only=False,
                awaiting_first_buy=symbol in awaiting,
            )
        )

    for symbol in exit_only:
        if symbol in pending_syms:
            continue
        prior = prior_assets.get(symbol, template)
        new_assets.append(
            _default_asset_row(
                symbol,
                float(prior.get("buy_rise_pct", 2.0)),
                float(prior.get("sell_drop_pct", 4.0)),
                prior,
                exit_only=True,
                awaiting_first_buy=False,
            )
        )

    config["assets"] = new_assets
    if new_assets:
        config["symbol"] = new_assets[0]["symbol"]
        config["buy_rise_pct"] = new_assets[0]["buy_rise_pct"]
        config["sell_drop_pct"] = new_assets[0]["sell_drop_pct"]

    assets_state = state.get("assets")
    if not isinstance(assets_state, dict):
        assets_state = {}
    pending_cash: dict[str, float] = {}
    for row in symbols:
        if isinstance(row, PendingSymbol) and row.allocated_cash is not None:
            pending_cash[row.symbol.upper()] = float(row.allocated_cash)
        elif isinstance(row, dict) and row.get("allocated_cash") is not None:
            pending_cash[str(row["symbol"]).upper()] = float(row["allocated_cash"])

    for asset in new_assets:
        sym = asset["symbol"]
        if sym not in assets_state:
            seed = pending_cash.get(sym, initial_cash)
            assets_state[sym] = _default_state_row(seed)
        elif sym in pending_cash and float(assets_state[sym].get("shares") or 0.0) <= 0:
            assets_state[sym]["cash"] = pending_cash[sym]
        # Persist soft-rotate flags beside strategy fields for the worker.
        assets_state[sym]["exit_only"] = bool(asset.get("exit_only", False))
        assets_state[sym]["awaiting_first_buy"] = bool(asset.get("awaiting_first_buy", False))
    state["assets"] = assets_state

    _atomic_write_json(config_path, config)
    _atomic_write_json(state_path, state)
    return config


def apply_to_paper_v1(
    config_path: Path,
    state_path: Path,
    symbols: Sequence[PendingSymbol | dict],
    **kwargs: Any,
) -> dict[str, Any]:
    return apply_to_paper_version(config_path, state_path, symbols, **kwargs)


def apply_to_paper_v2(
    config_path: Path,
    state_path: Path,
    symbols: Sequence[PendingSymbol | dict],
    **kwargs: Any,
) -> dict[str, Any]:
    return apply_to_paper_version(config_path, state_path, symbols, **kwargs)
