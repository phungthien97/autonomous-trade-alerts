"""Apply picker selection into state_live config.json (+ sleeve cash)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from app.live.config import LiveConfig, SymbolParams, load_live_config, save_live_config
from app.picker.pending import PendingSymbol


def apply_to_live_config(
    config_path: Path,
    symbols: Sequence[PendingSymbol | dict],
    *,
    extra_symbols: Sequence[str] | None = None,
) -> LiveConfig:
    """Update live symbols + thresholds; preserve mode/trading_enabled/etc.

    ``symbols`` are the pending (target) names with buy_rise/sell_drop as fractions.
    ``extra_symbols`` (e.g. exit_only drops) are appended to ``config.symbols`` so the
    live worker can still process sells; they keep prior asset params when present.
    """
    path = Path(config_path)
    if path.is_file():
        cfg = load_live_config(path)
    else:
        cfg = LiveConfig()

    prior_by_symbol = {a.symbol: a for a in cfg.assets}
    new_assets: list[SymbolParams] = []
    target_symbols: list[str] = []

    for row in symbols:
        if isinstance(row, PendingSymbol):
            symbol = row.symbol
            buy_rise = row.buy_rise
            sell_drop = row.sell_drop
        else:
            symbol = str(row["symbol"])
            buy_rise = float(row["buy_rise"])
            sell_drop = float(row["sell_drop"])
        target_symbols.append(symbol)
        new_assets.append(
            SymbolParams(
                symbol=symbol,
                buy_rise_pct=round(float(buy_rise) * 100.0, 6),
                sell_drop_pct=round(float(sell_drop) * 100.0, 6),
                enabled=True,
            )
        )

    for symbol in extra_symbols or []:
        if symbol in target_symbols:
            continue
        target_symbols.append(symbol)
        prior = prior_by_symbol.get(symbol)
        if prior is not None:
            new_assets.append(prior)
        else:
            new_assets.append(SymbolParams(symbol=symbol))

    cfg.symbols = target_symbols
    cfg.assets = new_assets
    save_live_config(path, cfg)
    return cfg


def apply_allocated_cash_to_live_state(
    state_path: Path,
    symbols: Sequence[PendingSymbol | dict],
    *,
    equal_fallback_total: float | None = None,
) -> None:
    """Set flat-sleeve cash from picker ``allocated_cash`` (priority whole-share split).

    Does not change sleeves that already hold shares. Missing allocation falls back
    to equal split of ``equal_fallback_total`` when provided.
    """
    path = Path(state_path)
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = {"assets": {}, "cash_usd": 0.0, "orders_today": 0, "reject_streak": 0}
    assets = raw.setdefault("assets", {})
    if not isinstance(assets, dict):
        assets = {}
        raw["assets"] = assets

    n = max(1, len(list(symbols)))
    equal = (
        float(equal_fallback_total) / float(n)
        if equal_fallback_total is not None and equal_fallback_total > 0
        else None
    )

    for row in symbols:
        if isinstance(row, PendingSymbol):
            symbol = row.symbol
            allocated = row.allocated_cash
        else:
            symbol = str(row["symbol"])
            allocated = row.get("allocated_cash")
        if not symbol:
            continue
        entry = assets.get(symbol)
        if not isinstance(entry, dict):
            entry = {
                "cash": 0.0,
                "shares": 0.0,
                "peak": None,
                "trough": None,
                "last_price": None,
            }
            assets[symbol] = entry
        if float(entry.get("shares") or 0.0) > 0:
            continue
        if allocated is not None:
            entry["cash"] = float(allocated)
        elif equal is not None:
            entry["cash"] = float(equal)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
