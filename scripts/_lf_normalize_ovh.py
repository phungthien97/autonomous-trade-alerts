#!/usr/bin/env python3
"""Strip CRLF from deployed Python modules on OVH."""
from pathlib import Path

root = Path("/opt/autonomous-trade-alerts")
paths = [
    "app/picker/hard_rotate.py",
    "app/picker/active.py",
    "app/picker/apply.py",
    "app/picker/__init__.py",
    "app/picker/apply_paper.py",
    "app/live_worker.py",
    "app/live/budget.py",
    "app/live/control.py",
    "app/remote/ui.py",
    "scripts/_convert_soft_to_hard_rotate.py",
]
for rel in paths:
    p = root / rel
    data = p.read_bytes()
    fixed = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if fixed != data:
        p.write_bytes(fixed)
        print("lf", rel)
    else:
        print("ok", rel)
