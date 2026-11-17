#!/usr/bin/env python3
"""Focus on NCLH leftover + what invested is counting."""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

ROOT = Path("/opt/autonomous-trade-alerts")
LIVE = ROOT / "state_live"


def parse_cycle(s: str):
    try:
        fixed = s.replace("'", '"').replace("None", "null").replace("True", "true").replace("False", "false")
        return json.loads(fixed)
    except Exception:
        try:
            return ast.literal_eval(s)
        except Exception:
            return None


def main() -> None:
    print("=== state / idempotency / queue ===")
    st = json.loads((LIVE / "state.json").read_text(encoding="utf-8"))
    print("NCLH asset", (st.get("assets") or {}).get("NCLH"))
    print("all shares", {k: (v or {}).get("shares") for k, v in (st.get("assets") or {}).items()})
    idem = json.loads((LIVE / "idempotency.json").read_text(encoding="utf-8"))
    print("idempotency", json.dumps(idem, indent=2)[:4000])
    print("queue", (LIVE / "queue.json").read_text(encoding="utf-8"))

    out = subprocess.check_output(
        [
            "journalctl",
            "-u",
            "live-worker.service",
            "--since",
            "2026-11-03 14:30:00",
            "--until",
            "2026-11-03 15:00:00",
            "--no-pager",
            "-o",
            "cat",
        ],
        text=True,
    )
    print("=== first 30min after open ===")
    for line in out.splitlines():
        if line.strip().startswith("{"):
            data = parse_cycle(line.strip())
            if not data:
                print("parsefail", line[:120])
                continue
            for d in data.get("decisions") or []:
                if d.get("symbol") == "NCLH":
                    print(
                        "NCLH",
                        d.get("signal"),
                        d.get("action"),
                        "sh",
                        d.get("shares"),
                        "px",
                        d.get("price"),
                        (d.get("signal_reason") or "")[:90],
                    )
            print("acts", data.get("actions"), "inv", data.get("invested_usd"))
        else:
            print(line[:240])

    # IBKR positions
    print("=== broker positions ===")
    try:
        import os
        import sys

        sys.path.insert(0, str(ROOT))
        os.chdir(ROOT)
        from app.broker.factory import make_broker

        broker = make_broker("ibkr")
        broker.connect()
        pos = broker.get_positions()
        print("positions", pos)
        snap = broker.get_account_snapshot() if hasattr(broker, "get_account_snapshot") else None
        if snap:
            print("snap", snap)
        broker.disconnect()
    except Exception as e:
        print("broker fail", type(e).__name__, e)
        # fallback: try account via existing helper scripts
        try:
            from app.account_snapshot import fetch_snapshot

            print(fetch_snapshot())
        except Exception as e2:
            print("snapshot fail", type(e2).__name__, e2)


if __name__ == "__main__":
    main()
