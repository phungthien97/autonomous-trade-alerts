#!/usr/bin/env python3
"""OVH one-shot: sync NCLH local state to broker truth during stuck flatten.

Clears optimistic exit_pending/zero shares and drops failed Nov 3 NCLH SELL
idempotency keys so the next RTH cycle can flatten cleanly with wait-for-fill.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/opt/autonomous-trade-alerts")
LIVE = ROOT / "state_live"


def main() -> None:
    state_path = LIVE / "state.json"
    idem_path = LIVE / "idempotency.json"
    active_path = ROOT / "state_picker" / "active_selection.json"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assets = state.setdefault("assets", {})
    nclh = assets.get("NCLH") or {}
    print("before_nclh", nclh)

    # Broker truth from last cycle / known stuck size; prefer live read if possible.
    broker_shares = 3228.0
    try:
        import os
        import sys

        sys.path.insert(0, str(ROOT))
        os.chdir(ROOT)
        os.environ.setdefault("IB_CLIENT_ID", "97")
        from app.broker.ibkr import IbkrBroker

        b = IbkrBroker()
        try:
            pos = b.get_positions()
            broker_shares = float(pos.get("NCLH", 0.0) or 0.0)
            print("broker_positions_nonzero", {k: v for k, v in pos.items() if abs(float(v)) > 1e-9})
        finally:
            b.ib.disconnect()
    except Exception as exc:  # noqa: BLE001
        print("broker_read_failed", type(exc).__name__, exc, "using", broker_shares)

    nclh["shares"] = max(0.0, broker_shares)
    nclh["exit_pending"] = False
    if broker_shares > 1e-9 and nclh.get("peak") is None:
        # Restore a peak so post-flatten strategy state is sane if needed.
        nclh["peak"] = float(nclh.get("last_price") or 17.5)
    assets["NCLH"] = nclh
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("after_nclh", nclh)

    idem = json.loads(idem_path.read_text(encoding="utf-8"))
    keys = idem.get("keys") or {}
    removed = []
    for k in list(keys):
        if k.startswith("NCLH|") and "|SELL" in k and "2026-11-03" in k:
            removed.append(k)
            del keys[k]
    idem["keys"] = keys
    idem_path.write_text(json.dumps(idem, indent=2), encoding="utf-8")
    print("removed_idempotency", removed)

    active = json.loads(active_path.read_text(encoding="utf-8"))
    print("rotation_phase", active.get("rotation_phase"))
    print("symbols", [(s.get("symbol"), s.get("exit_only"), s.get("awaiting_first_buy")) for s in active.get("symbols") or []])
    print("reconciled_ok")


if __name__ == "__main__":
    main()
