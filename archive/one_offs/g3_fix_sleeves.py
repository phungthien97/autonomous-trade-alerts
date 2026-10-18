"""One-shot OVH G3 unblock: sleeve cash must afford ≥1 whole share."""
from __future__ import annotations

import json
from pathlib import Path

CFG = Path("/opt/autonomous-trade-alerts/state_live/config.json")
STATE = Path("/opt/autonomous-trade-alerts/state_live/state.json")


def main() -> None:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    st = json.loads(STATE.read_text(encoding="utf-8"))
    cfg["total_cash"] = 3000.0
    cfg["allow_fractional_default"] = False
    CFG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    for row in (st.get("assets") or {}).values():
        row["cash"] = 1000.0
    STATE.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    print("config total_cash", cfg["total_cash"], "fractional", cfg["allow_fractional_default"])
    print("sleeves", {k: v.get("cash") for k, v in st["assets"].items()})


if __name__ == "__main__":
    main()
