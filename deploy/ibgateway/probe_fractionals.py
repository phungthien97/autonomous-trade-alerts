#!/usr/bin/env python3
"""Probe IBKR paper for fractional eligibility on live symbols (R3)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, MarketOrder, Stock


SYMBOLS = ["MSFT", "AAPL", "SMH", "VOO"]  # VOO for completeness from investigation


@dataclass
class Row:
    symbol: str
    con_id: int | None
    min_size: float | None
    size_increment: float | None
    fractional: bool | None
    note: str


def _as_float(val) -> float | None:
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def probe(symbol: str, ib: IB) -> Row:
    contract = Stock(symbol, "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        return Row(symbol, None, None, None, None, "qualify_failed")
    c = qualified[0]
    details = ib.reqContractDetails(c)
    ib.sleep(1)
    if not details:
        return Row(symbol, int(c.conId), None, None, None, "no_contract_details")
    d = details[0]
    min_size = _as_float(getattr(d, "minSize", None))
    size_inc = _as_float(getattr(d, "sizeIncrement", None))
    # Heuristic used by IB docs/community: sizeIncrement < 1 => fractional lots allowed
    fractional = None
    note_parts = []
    if size_inc is not None:
        fractional = size_inc < 1.0 - 1e-12
        note_parts.append(f"sizeIncrement={size_inc}")
    else:
        note_parts.append("sizeIncrement_missing")
    if min_size is not None:
        note_parts.append(f"minSize={min_size}")
    # Optional what-if: fractional market buy of 0.1 share (paper only; dry via whatIf)
    try:
        order = MarketOrder("BUY", 0.1)
        # whatIfOrder if available
        if hasattr(ib, "whatIfOrder"):
            w = ib.whatIfOrder(c, order)
            ib.sleep(1)
            if w is not None:
                note_parts.append(f"whatIf_status={getattr(w, 'status', w)}")
                # If IB rejects fractional, commission/initMargin often empty + error later
    except Exception as exc:  # noqa: BLE001
        note_parts.append(f"whatIf_err={type(exc).__name__}")
    return Row(symbol, int(c.conId), min_size, size_inc, fractional, "; ".join(note_parts))


def main() -> int:
    ib = IB()
    ib.connect("127.0.0.1", 4002, clientId=17)
    print("account", ib.managedAccounts())
    rows = [probe(sym, ib) for sym in SYMBOLS]
    ib.disconnect()
    print()
    print(f"{'symbol':<6} {'fractional':<11} {'minSize':<10} {'sizeInc':<10} note")
    for r in rows:
        print(
            f"{r.symbol:<6} {str(r.fractional):<11} {str(r.min_size):<10} {str(r.size_increment):<10} {r.note}"
        )
    # Summary for our live trio
    live = [r for r in rows if r.symbol in {"MSFT", "AAPL", "SMH"}]
    ok = all(r.fractional is True for r in live)
    print()
    print("LIVE_TRIO_ALL_FRACTIONAL" if ok else "LIVE_TRIO_NOT_ALL_FRACTIONAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
