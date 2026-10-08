#!/usr/bin/env python3
"""Probe IBKR paper historical hourly bars vs Yahoo (R6 / R9)."""
from __future__ import annotations

import asyncio
import math
import sys
from dataclasses import dataclass

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock

SYMBOLS = ["MSFT", "AAPL", "SMH", "VOO"]
DURATION = "5 D"
BAR_SIZE = "1 hour"


@dataclass
class ProbeResult:
    symbol: str
    ok: bool
    n_rth: int
    n_all: int
    last_rth_close: float | None
    last_rth_ts: str | None
    yahoo_close: float | None
    yahoo_ts: str | None
    abs_diff_pct: float | None
    note: str


def _yahoo_last(symbol: str) -> tuple[float | None, str | None, str]:
    try:
        import yfinance as yf
    except ImportError:
        return None, None, "yfinance_missing"
    try:
        hist = yf.Ticker(symbol).history(period="5d", interval="1h")
        if hist is None or hist.empty:
            return None, None, "yahoo_empty"
        last = hist.iloc[-1]
        idx = hist.index[-1]
        ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
        return float(last["Close"]), ts, "ok"
    except Exception as exc:  # noqa: BLE001
        return None, None, f"yahoo_err={type(exc).__name__}:{exc}"


def _fetch_bars(ib: IB, symbol: str, use_rth: bool):
    contract = Stock(symbol, "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        return None, "qualify_failed"
    c = qualified[0]
    # formatDate=2 → unix epoch (avoids ZoneInfo/US-Eastern tzdata on minimal hosts)
    bars = ib.reqHistoricalData(
        c,
        endDateTime="",
        durationStr=DURATION,
        barSizeSetting=BAR_SIZE,
        whatToShow="TRADES",
        useRTH=use_rth,
        formatDate=2,
        keepUpToDate=False,
    )
    ib.sleep(1)
    return bars, "ok"


def probe(symbol: str, ib: IB) -> ProbeResult:
    notes: list[str] = []
    try:
        bars_rth, note_rth = _fetch_bars(ib, symbol, use_rth=True)
        if note_rth != "ok":
            return ProbeResult(symbol, False, 0, 0, None, None, None, None, None, note_rth)
        bars_all, note_all = _fetch_bars(ib, symbol, use_rth=False)
        if note_all != "ok":
            notes.append(note_all)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(
            symbol, False, 0, 0, None, None, None, None, None, f"ib_err={type(exc).__name__}:{exc}"
        )

    n_rth = len(bars_rth or [])
    n_all = len(bars_all or [])
    if n_rth == 0:
        # Common when complimentary data missing / delayed entitlement issue
        return ProbeResult(
            symbol,
            False,
            0,
            n_all,
            None,
            None,
            None,
            None,
            None,
            f"ib_rth_empty n_all={n_all}; check market data entitlements",
        )

    last = bars_rth[-1]
    ib_close = float(last.close)
    ib_ts = str(last.date)
    y_close, y_ts, y_note = _yahoo_last(symbol)
    notes.append(f"yahoo={y_note}")
    diff = None
    if y_close is not None and y_close > 0:
        diff = abs(ib_close - y_close) / y_close * 100.0
        notes.append(f"abs_diff_pct={diff:.3f}")

    # Strategy alignment signals
    if n_all > n_rth:
        notes.append(f"ext_hours_extra_bars={n_all - n_rth}")
    else:
        notes.append("no_extra_ext_bars_in_window")

    ok = n_rth >= 5 and (diff is None or diff < 2.0 or math.isnan(diff))
    return ProbeResult(
        symbol,
        ok,
        n_rth,
        n_all,
        ib_close,
        ib_ts,
        y_close,
        y_ts,
        diff,
        "; ".join(notes),
    )


def main() -> int:
    host = "127.0.0.1"
    port = 4002
    client_id = int(__import__("os").environ.get("IB_CLIENT_ID", "91"))
    ib = IB()
    print(f"connecting {host}:{port} clientId={client_id}")
    ib.connect(host, port, clientId=client_id)
    print("account", ib.managedAccounts())

    # Snapshot of market-data related account values if present
    for tag in ("PreviousEquityWithLoanValue",):
        pass
    md_notes = []
    for av in ib.accountValues():
        if "MarketData" in (av.tag or "") or "Data" in (av.tag or "") and "Fee" in (av.tag or ""):
            md_notes.append(f"{av.tag}={av.value}{av.currency}")
    if md_notes:
        print("account_data_tags", "; ".join(md_notes[:20]))

    rows = [probe(sym, ib) for sym in SYMBOLS]
    ib.disconnect()

    print()
    hdr = (
        f"{'symbol':<6} {'ok':<5} {'n_rth':<6} {'n_all':<6} "
        f"{'ib_close':<10} {'yb_close':<10} {'diff%':<8} note"
    )
    print(hdr)
    for r in rows:
        print(
            f"{r.symbol:<6} {str(r.ok):<5} {r.n_rth:<6} {r.n_all:<6} "
            f"{str(r.last_rth_close) if r.last_rth_close is not None else '-':<10} "
            f"{str(r.yahoo_close) if r.yahoo_close is not None else '-':<10} "
            f"{(f'{r.abs_diff_pct:.3f}' if r.abs_diff_pct is not None else '-'):<8} "
            f"{r.note}"
        )
        if r.last_rth_ts:
            print(f"       ib_last_ts={r.last_rth_ts} yahoo_last_ts={r.yahoo_ts}")

    live = [r for r in rows if r.symbol in {"MSFT", "AAPL", "SMH"}]
    if all(r.ok for r in live):
        print()
        print("R6_IB_HOURLY_OK_FOR_LIVE_TRIO")
        return 0
    print()
    print("R6_IB_HOURLY_NOT_OK")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
