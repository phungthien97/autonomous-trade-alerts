"""Apply picker selection into state_live config.json."""

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
