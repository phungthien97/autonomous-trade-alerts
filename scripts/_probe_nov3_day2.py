#!/usr/bin/env python3
"""Deeper Nov 3 hard-rotate day: RTH cycles, submits, residual positions."""
from __future__ import annotations

import ast
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/opt/autonomous-trade-alerts")
LIVE = ROOT / "state_live"


def parse_cycle(s: str):
    try:
        return json.loads(
            s.replace("'", '"')
            .replace("None", "null")
            .replace("True", "true")
            .replace("False", "false")
        )
    except Exception:
        try:
            return ast.literal_eval(s)
        except Exception:
            return None


def main() -> None:
    out = subprocess.check_output(
        [
            "journalctl",
            "-u",
            "live-worker.service",
            "--since",
            "2026-11-03 13:00:00",  # ~8am ET
            "--until",
            "2026-11-04 01:00:00",  # ~8pm ET
            "--no-pager",
            "-o",
            "short-iso",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )

    cycles = []
    other = []
    for line in out.splitlines():
        # strip journal prefix to find {
        idx = line.find("{")
        if idx >= 0 and "actions" in line:
            data = parse_cycle(line[idx:])
            if data and isinstance(data, dict) and "actions" in data:
                ts = line[:32]
                cycles.append((ts, data))
                continue
        low = line.lower()
        if any(
            k in low
            for k in (
                "submitted",
                "filled",
                "flatten complete",
                "hard rotate",
                "blocked",
                "error",
                "reject",
                "pruned",
                "idle",
                "order",
            )
        ):
            other.append(line)

    print("=== RTH / ACTION CYCLES (non-empty or rth true) ===")
    action_hist = Counter()
    invested_series = []
    for ts, data in cycles:
        acts = data.get("actions") or []
        rth = data.get("rth_ok")
        if not acts and not rth:
            continue
        invested_series.append(
            (
                ts,
                rth,
                data.get("invested_usd"),
                data.get("cash_usd"),
                data.get("spendable_usd"),
                acts,
            )
        )
        for a in acts:
            action_hist[a] += 1
        # print interesting
        interesting = bool(acts) or any(
            (d.get("signal") or d.get("action") or d.get("gate"))
            for d in (data.get("decisions") or [])
        )
        if interesting and (rth or acts):
            print(
                ts,
                "rth=",
                rth,
                "inv=",
                round(float(data.get("invested_usd") or 0), 2),
                "cash=",
                round(float(data.get("cash_usd") or 0), 2),
                "acts=",
                acts,
            )
            for d in data.get("decisions") or []:
                if not (d.get("signal") or d.get("action") or d.get("gate")):
                    continue
                print(
                    "   ",
                    d.get("symbol"),
                    d.get("signal"),
                    d.get("action"),
                    "sh=",
                    d.get("shares"),
                    "px=",
                    d.get("price"),
                    "sma=",
                    d.get("sma20"),
                    "gate=",
                    d.get("gate"),
                    "|",
                    (d.get("signal_reason") or "")[:100],
                )

    print("\n=== ACTION COUNTS ===")
    for k, v in action_hist.most_common():
        print(f"  {k}: {v}")

    print("\n=== INVESTED PATH (first/last + big deltas) ===")
    prev = None
    for row in invested_series:
        ts, rth, inv, cash, spend, acts = row
        invf = float(inv or 0)
        if prev is None:
            print("START", ts, "rth", rth, "inv", invf, "cash", cash, "acts", acts)
        else:
            dinv = invf - prev
            if abs(dinv) > 500 or acts:
                print(
                    ts,
                    "rth",
                    rth,
                    "inv",
                    round(invf, 2),
                    "dInv",
                    round(dinv, 2),
                    "cash",
                    round(float(cash or 0), 2),
                    "acts",
                    acts,
                )
        prev = invf
    if invested_series:
        ts, rth, inv, cash, spend, acts = invested_series[-1]
        print("END", ts, "rth", rth, "inv", inv, "cash", cash, "spendable", spend, "acts", acts)

    print("\n=== OTHER LOG LINES (sample) ===")
    for line in other[:120]:
        print(line[:260])
    print("... total other", len(other))

    # state + active + any local trade logs
    print("\n=== FILES UNDER state_live ===")
    for p in sorted(LIVE.iterdir()):
        print(p.name, p.stat().st_size)

    active = json.loads((ROOT / "state_picker" / "active_selection.json").read_text())
    print("\nphase", active.get("rotation_phase"), "n", len(active.get("symbols") or []))
    for s in active.get("symbols") or []:
        print(s)

    last = json.loads((LIVE / "last_cycle.json").read_text())
    print(
        "\nlast invested",
        last.get("invested_usd"),
        "gross",
        last.get("gross_position_value_usd"),
        "cash",
        last.get("cash_usd"),
        "budget",
        last.get("trading_budget_usd"),
        "book",
        last.get("book_equity"),
    )

    # Try broker positions via a lightweight import if gateway up — skip if fails
    print("\n=== ATTEMPT BROKER POSITIONS ===")
    try:
        import os
        import sys

        sys.path.insert(0, str(ROOT))
        os.chdir(ROOT)
        # Don't open IBKR from probe — look at account_snapshot if present
        snap = LIVE / "account_snapshot.json"
        if snap.is_file():
            s = json.loads(snap.read_text())
            print("snapshot keys", list(s)[:20])
            pos = s.get("positions") or s.get("portfolio") or s
            print(json.dumps(pos, indent=2)[:4000])
        else:
            print("no account_snapshot.json")
        # last_cycle may embed nothing; check state assets fully
        st = json.loads((LIVE / "state.json").read_text())
        print("state assets:")
        for sym, row in (st.get("assets") or {}).items():
            print(" ", sym, row)
    except Exception as e:
        print("broker/state err", e)


if __name__ == "__main__":
    main()
