"""Dig into Nov 2 anomalous AMGN buy + FICO orders + sizing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

APP = Path("/opt/autonomous-trade-alerts")


def main() -> None:
    audit = APP / "state_live" / "audit" / "events.jsonl"
    print("=== RAW AUDIT NOV2 ===")
    for line in audit.read_text(encoding="utf-8", errors="replace").splitlines():
        if "2026-11-02" not in line:
            continue
        o = json.loads(line)
        print(json.dumps(o, indent=2)[:2000])
        print("---")

    print("=== JOURNAL CYCLES WITH ACTIONS ===")
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
        try:
            # line may start with noise; find dict
            i = line.find("{")
            if i < 0:
                continue
            d = json.loads(line[i].replace("'", '"') if False else line[i:])
        except Exception:
            # python dict repr — eval carefully via ast
            import ast

            i = line.find("{")
            try:
                d = ast.literal_eval(line[i:])
            except Exception as exc:
                print("parse_fail", exc, line[:200])
                continue
        actions = d.get("actions") or []
        if not actions:
            continue
        print("ACTIONS", actions)
        print(
            "  cash=",
            d.get("cash_usd"),
            "invested=",
            d.get("invested_usd"),
            "spendable=",
            d.get("spendable_usd"),
            "orders_today=",
            d.get("orders_today"),
        )
        for dec in d.get("decisions") or []:
            if dec.get("action") or dec.get("signal") or (dec.get("symbol") in {a.split(":")[0] for a in actions}):
                print(
                    f"  {dec.get('symbol')}: signal={dec.get('signal')} action={dec.get('action')} "
                    f"gate={dec.get('gate')} shares={dec.get('shares')} px={dec.get('price')} "
                    f"sma={dec.get('sma20')} plan={dec.get('plan')}"
                )
                print(f"    reason={dec.get('signal_reason')}")
        print()

    # Check whether exit_only was on AMGN in active file mtime vs buy time
    active = json.loads((APP / "state_picker" / "active_selection.json").read_text())
    print("active applied_at", active.get("applied_at"))
    for s in active["symbols"]:
        if s["symbol"] in {"AMGN", "P", "HUM", "VLO", "MRNA", "FICO"}:
            print(s)

    # broker positions now
    print("=== compare invested vs gross ===")
    last = json.loads((APP / "state_live" / "last_cycle.json").read_text())
    print("invested_usd", last.get("invested_usd"))
    print("gross_position_value_usd", last.get("gross_position_value_usd"))
    print("book_equity", last.get("book_equity"))
    print("cash_usd", last.get("cash_usd"))
    print("spendable_usd", last.get("spendable_usd"))


if __name__ == "__main__":
    main()
