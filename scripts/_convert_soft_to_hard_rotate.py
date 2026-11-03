"""One-shot OVH: convert mid soft-rotate book into hard-rotate flattening.

Sets rotation_phase=flattening, marks all target sleeves awaiting_first_buy,
keeps non-target leftovers as exit_only. Next RTH worker cycles force-sell
everything, then SMA20-enter the target slate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.live.config import load_live_config, save_live_config
from app.paths import LivePaths, PickerPaths
from app.picker.active import (
    ROTATION_FLATTENING,
    ActiveSelection,
    ActiveSymbol,
    load_active,
    save_active,
)


def main() -> None:
    picker = PickerPaths()
    live = LivePaths()
    active = load_active(picker.active_selection_path)
    if active is None:
        raise SystemExit("no active_selection.json")
    cfg = load_live_config(live.config_path)

    targets = [s for s in active.symbols if not s.exit_only]
    drops = [s for s in active.symbols if s.exit_only]
    if not targets:
        # Fall back to config symbols that aren't exit_only rows
        drop_set = {d.symbol for d in drops}
        targets = [
            ActiveSymbol(str(sym), 0.02, 0.04, awaiting_first_buy=True)
            for sym in cfg.symbols
            if str(sym) not in drop_set
        ]

    now = datetime.now(timezone.utc).isoformat()
    new_rows: list[ActiveSymbol] = []
    for row in targets:
        new_rows.append(
            ActiveSymbol(
                symbol=row.symbol,
                buy_rise=row.buy_rise,
                sell_drop=row.sell_drop,
                exit_only=False,
                awaiting_first_buy=True,
                joined_at=row.joined_at or now,
            )
        )
    for row in drops:
        new_rows.append(
            ActiveSymbol(
                symbol=row.symbol,
                buy_rise=row.buy_rise,
                sell_drop=row.sell_drop,
                exit_only=True,
                awaiting_first_buy=False,
                joined_at=row.joined_at,
            )
        )

    # Ensure live config lists targets + drops so flatten can sell leftovers.
    target_syms = [r.symbol for r in new_rows if not r.exit_only]
    drop_syms = [r.symbol for r in new_rows if r.exit_only]
    prior_assets = {a.symbol: a for a in cfg.assets}
    new_assets = []
    for sym in target_syms + drop_syms:
        if sym in prior_assets:
            new_assets.append(prior_assets[sym])
        else:
            from app.live.config import SymbolParams

            new_assets.append(SymbolParams(symbol=sym))
    cfg.symbols = target_syms + drop_syms
    cfg.assets = new_assets
    save_live_config(live.config_path, cfg)

    converted = ActiveSelection(
        applied_at=active.applied_at,
        run_id=active.run_id,
        symbols=new_rows,
        rotation_phase=ROTATION_FLATTENING,
    )
    save_active(picker.active_selection_path, converted)

    # Clear peaks so strategy doesn't fight hard-rotate force sells; worker
    # overrides signals while flattening anyway.
    if live.state_path.is_file():
        raw = json.loads(live.state_path.read_text(encoding="utf-8"))
        assets = raw.get("assets") or {}
        if isinstance(assets, dict):
            for sym, row in assets.items():
                if isinstance(row, dict):
                    row["exit_pending"] = False
        raw["hard_rotate_converted_at"] = now
        live.state_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    print("converted_to_hard_rotate_flattening")
    print("targets", target_syms)
    print("exit_only", drop_syms)
    print("rotation_phase", converted.rotation_phase)


if __name__ == "__main__":
    main()
