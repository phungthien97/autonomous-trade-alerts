"""Confirm first-buy SMA/awaiting and post-AMGN prune behavior."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

APP = Path("/opt/autonomous-trade-alerts")


def cycles_with_actions():
    out = subprocess.check_output(
        [
            "bash",
            "-lc",
            "journalctl -u live-worker.service --since '2026-11-02 09:00:00' "
            "--until '2026-11-02 17:00:00' --no-pager -o cat 2>/dev/null | "
            "grep -E \"'actions': \\['\" || true",
        ],
        text=True,
    )
    for line in out.splitlines():
        i = line.find("{")
        if i < 0:
            continue
        yield ast.literal_eval(line[i:])


def main() -> None:
    print("=== FIRST BUYS: sma vs price, gate ===")
    for d in cycles_with_actions():
        for dec in d.get("decisions") or []:
            if dec.get("signal") == "BUY" and dec.get("action"):
                px = float(dec["price"])
                sma = dec.get("sma20")
                print(
                    dec["symbol"],
                    "px",
                    px,
                    "sma20",
                    sma,
                    "above" if sma is not None and px > float(sma) else "?",
                    "gate",
                    dec.get("gate"),
                    "awaiting_hint",
                    "first" if dec.get("shares") == 0 else "add",
                )

    print("=== AMGN around sell: shares before/after in neighboring cycles ===")
    out = subprocess.check_output(
        [
            "bash",
            "-lc",
            "journalctl -u live-worker.service --since '2026-11-02 15:15:00' "
            "--until '2026-11-02 15:35:00' --no-pager -o cat 2>/dev/null | "
            "grep -E \"^\\{\" || true",
        ],
        text=True,
    )
    for line in out.splitlines():
        i = line.find("{")
        if i < 0:
            continue
        try:
            d = ast.literal_eval(line[i:])
        except Exception:
            continue
        for dec in d.get("decisions") or []:
            if dec.get("symbol") == "AMGN":
                print(
                    "AMGN",
                    "actions",
                    d.get("actions"),
                    "sh",
                    dec.get("shares"),
                    "sig",
                    dec.get("signal"),
                    "act",
                    dec.get("action"),
                    "gate",
                    dec.get("gate"),
                    "reason",
                    dec.get("signal_reason"),
                )

    print("=== PRUNE: flat exit_only still in active? ===")
    active = json.loads((APP / "state_picker" / "active_selection.json").read_text())
    state = json.loads((APP / "state_live" / "state.json").read_text())
    for s in active["symbols"]:
        if not s.get("exit_only"):
            continue
        sh = float((state.get("assets") or {}).get(s["symbol"], {}).get("shares") or 0)
        print(s["symbol"], "exit_only flat?" , sh <= 0, "shares", sh, "SHOULD_PRUNE" if sh <= 0 else "hold_until_sell")

    print("=== FICO share path ===")
    out = subprocess.check_output(
        [
            "bash",
            "-lc",
            "journalctl -u live-worker.service --since '2026-11-02 14:30:00' "
            "--until '2026-11-02 17:00:00' --no-pager -o cat 2>/dev/null | "
            "grep -E \"^\\{\" || true",
        ],
        text=True,
    )
    for line in out.splitlines():
        i = line.find("{")
        if i < 0:
            continue
        try:
            d = ast.literal_eval(line[i:])
        except Exception:
            continue
        for dec in d.get("decisions") or []:
            if dec.get("symbol") != "FICO":
                continue
            if dec.get("action") or dec.get("signal"):
                print(
                    "FICO",
                    d.get("actions"),
                    "sh",
                    dec.get("shares"),
                    "sig",
                    dec.get("signal"),
                    "act",
                    dec.get("action"),
                    "px",
                    dec.get("price"),
                    "peak",
                    dec.get("peak"),
                    "trough",
                    dec.get("trough"),
                )


if __name__ == "__main__":
    main()
