#!/usr/bin/env python3
"""Summarize Nov 3 hard-rotate / live day on OVH."""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/opt/autonomous-trade-alerts")
LIVE = ROOT / "state_live"
PICKER = ROOT / "state_picker"


def load(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    active = load(PICKER / "active_selection.json")
    cfg = load(LIVE / "config.json")
    state = load(LIVE / "state.json")
    last = load(LIVE / "last_cycle.json")
    audit = LIVE / "audit.jsonl"
    fills_path = LIVE / "fills.jsonl"
    journal = LIVE / "journal.jsonl"

    print("=== ACTIVE ===")
    if active:
        print("phase", active.get("rotation_phase"))
        print("applied_at", active.get("applied_at"), "run", active.get("run_id"))
        for s in active.get("symbols") or []:
            print(
                " ",
                s.get("symbol"),
                "exit_only=",
                s.get("exit_only"),
                "await=",
                s.get("awaiting_first_buy"),
                "buy/sell%",
                s.get("buy_rise"),
                s.get("sell_drop"),
            )

    print("\n=== CONFIG ===")
    if cfg:
        print("symbols", cfg.get("symbols"))
        print("budget", cfg.get("trading_budget_usd"))
        print("mode", cfg.get("mode"), "enabled", cfg.get("trading_enabled"))
        print("daily_order_cap", cfg.get("daily_order_cap"))

    print("\n=== STATE SHARES / FLAGS ===")
    if state:
        assets = state.get("assets") or {}
        for sym, row in assets.items():
            if not isinstance(row, dict):
                continue
            sh = float(row.get("shares") or 0)
            if sh > 1e-9 or row.get("awaiting_first_buy") or row.get("exit_only"):
                print(
                    sym,
                    "shares=",
                    sh,
                    "peak=",
                    row.get("peak"),
                    "trough=",
                    row.get("trough"),
                    "await=",
                    row.get("awaiting_first_buy"),
                    "exit=",
                    row.get("exit_only"),
                )
        print("hard_rotate_converted_at", state.get("hard_rotate_converted_at"))

    print("\n=== LAST CYCLE ===")
    if last:
        print("rth_ok", last.get("rth_ok"), "cash", last.get("cash_usd"), "invested", last.get("invested_usd"))
        print("budget", last.get("trading_budget_usd"), "spendable", last.get("spendable_usd"))
        print("available", last.get("available_funds_usd"), "book_equity", last.get("book_equity"))
        print("actions", last.get("actions"))
        print("orders_today", last.get("orders_today"), last.get("orders_today_by_symbol"))
        for d in last.get("decisions") or []:
            print(
                d.get("symbol"),
                "sig=",
                d.get("signal"),
                "act=",
                d.get("action"),
                "plan=",
                d.get("plan"),
                "gate=",
                d.get("gate"),
                "sh=",
                d.get("shares"),
                "px=",
                d.get("price"),
                "sma=",
                d.get("sma20"),
                "|",
                (d.get("signal_reason") or "")[:120],
            )

    # Journal / fills today UTC and ET-ish (Nov 3)
    day_keys = ("2026-11-03", "2026-11-04")  # UTC evening spill
    print("\n=== JOURNAL / FILLS / AUDIT (Nov 3 window) ===")
    for label, path in [("journal", journal), ("fills", fills_path), ("audit", audit)]:
        if not path.is_file():
            print(label, "missing")
            continue
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            if not any(k in line for k in day_keys):
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"_raw": line[:200]})
        print(f"\n-- {label}: {len(rows)} lines --")
        for r in rows[-80:]:
            if "_raw" in r:
                print(r["_raw"])
                continue
            ts = r.get("ts") or r.get("time") or r.get("when") or r.get("timestamp") or ""
            kind = r.get("event") or r.get("type") or r.get("action") or r.get("side") or ""
            sym = r.get("symbol") or r.get("sym") or ""
            extras = {
                k: r.get(k)
                for k in (
                    "side",
                    "qty",
                    "shares",
                    "price",
                    "fill_price",
                    "status",
                    "reason",
                    "signal",
                    "order_id",
                    "gate",
                    "plan",
                    "message",
                    "why",
                )
                if r.get(k) is not None
            }
            print(ts, kind, sym, extras if extras else r)

    # systemd journal for hard rotate / submitted / filled
    print("\n=== SYSTEMD LIVE-WORKER (grep) ===")
    try:
        out = subprocess.check_output(
            [
                "journalctl",
                "-u",
                "live-worker.service",
                "--since",
                "2026-11-03 00:00:00",
                "--until",
                "2026-11-04 03:00:00",
                "--no-pager",
                "-o",
                "cat",
            ],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except Exception as e:
        print("journalctl failed", e)
        return
    keys = (
        "Hard rotate",
        "flatten",
        "submitted",
        "filled",
        "BUY",
        "SELL",
        "blocked",
        "queued",
        "awaiting",
        "sma",
        "SMA",
        "phase",
        "idle",
        "pruned",
        "exit_only",
        "budget",
        "deployable",
        "rebalance",
    )
    interesting = []
    for line in out.splitlines():
        if any(k.lower() in line.lower() for k in keys) or line.strip().startswith("{"):
            interesting.append(line)
    print("matched_lines", len(interesting), "total", len(out.splitlines()))
    # Print cycle summaries (JSON blobs) briefly
    buys = sells = queued = submitted = 0
    for line in interesting:
        low = line.lower()
        if "'signal': 'buy'" in low or '"signal": "buy"' in low or "signal': 'BUY'" in line:
            buys += 1
        if "signal': 'SELL'" in line or '"signal": "SELL"' in line:
            sells += 1
        if ":submitted" in line or "submitted" in low:
            submitted += 1
        if ":queued" in line:
            queued += 1
    print("approx cycle mentions buys/sells/queued/submitted", buys, sells, queued, submitted)

    # Extract every actions list from JSON cycle lines
    print("\n=== CYCLE ACTIONS TIMELINE ===")
    for line in out.splitlines():
        s = line.strip()
        if not (s.startswith("{") and "'actions'" in s or s.startswith("{") and '"actions"' in s):
            if not (s.startswith("{") and "actions" in s):
                continue
        try:
            # python dict repr from logging — try json then ast
            data = None
            try:
                data = json.loads(s.replace("'", '"').replace("None", "null").replace("True", "true").replace("False", "false"))
            except Exception:
                import ast

                data = ast.literal_eval(s)
            acts = data.get("actions") or []
            if not acts and data.get("rth_ok") is False:
                continue
            inv = data.get("invested_usd")
            cash = data.get("cash_usd")
            print(
                "rth=",
                data.get("rth_ok"),
                "invested=",
                inv,
                "cash=",
                cash,
                "budget=",
                data.get("trading_budget_usd"),
                "acts=",
                acts,
            )
            for d in data.get("decisions") or []:
                if d.get("action") or d.get("signal"):
                    print(
                        "  ",
                        d.get("symbol"),
                        d.get("signal"),
                        d.get("action"),
                        "sh",
                        d.get("shares"),
                        "px",
                        d.get("price"),
                        "gate",
                        d.get("gate"),
                        (d.get("signal_reason") or "")[:90],
                    )
        except Exception as e:
            if acts := None:
                pass
            if "Hard rotate" in s or ":submitted" in s or ":filled" in s or ":queued" in s:
                print(s[:300])


if __name__ == "__main__":
    main()
