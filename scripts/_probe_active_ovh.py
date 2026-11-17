#!/usr/bin/env python3
import json
from pathlib import Path

root = Path("/opt/autonomous-trade-alerts")
active_path = root / "state_picker" / "active_selection.json"
cfg_path = root / "state_live" / "config.json"
a = json.loads(active_path.read_text(encoding="utf-8"))
print("phase", a.get("rotation_phase"))
print("symbols", [(s["symbol"], s.get("exit_only"), s.get("awaiting_first_buy")) for s in a["symbols"]])
if cfg_path.is_file():
    c = json.loads(cfg_path.read_text(encoding="utf-8"))
    print("config_symbols", c.get("symbols"))
