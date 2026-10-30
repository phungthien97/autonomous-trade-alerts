"""Optional IBKR mark overlay for the remote dashboard (dedicated client id)."""

from __future__ import annotations

import os
from typing import Any, Callable

# Must not collide with live-worker (1) or picker-rank (7).
DASHBOARD_IB_CLIENT_ID_DEFAULT = 9


def dashboard_ib_client_id() -> int:
    raw = os.environ.get("DASHBOARD_IB_CLIENT_ID", str(DASHBOARD_IB_CLIENT_ID_DEFAULT))
    try:
        return int(raw)
    except ValueError:
        return DASHBOARD_IB_CLIENT_ID_DEFAULT


def overlay_ibkr_marks(
    live_status: dict[str, Any],
    *,
    broker_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of live_status with IBKR marks when reachable.

    On failure, returns the original file-based marks and ``marks_source="files"``.
    """
    out = dict(live_status)
    out["marks_source"] = "files"
    factory = broker_factory
    if factory is None:
        return out

    broker = None
    try:
        # Dedicated client id before IbkrBroker reads env (not worker=1 / picker=7).
        os.environ["IB_CLIENT_ID"] = str(dashboard_ib_client_id())
        broker = factory()
        snapshot = broker.get_account_snapshot()
        positions = broker.get_positions()
        out["cash_usd"] = getattr(snapshot, "cash_usd", out.get("cash_usd"))
        equity = getattr(snapshot, "equity_usd", None)
        if equity is not None:
            out["broker_equity_usd"] = float(equity)
        gross = getattr(snapshot, "gross_position_value_usd", None)
        if gross is not None:
            out["gross_position_value_usd"] = float(gross)
        accrued = getattr(snapshot, "accrued_cash_usd", None)
        if accrued is not None:
            out["accrued_cash_usd"] = float(accrued)
        avail = getattr(snapshot, "available_funds_usd", None)
        if avail is not None:
            out["available_funds_usd"] = float(avail)
        spendable = getattr(snapshot, "spendable_usd", None)
        if spendable is not None:
            out["spendable_usd"] = float(spendable)
        account_ccy = getattr(snapshot, "account_currency", None)
        if account_ccy:
            out["account_currency"] = str(account_ccy)
        rate = getattr(snapshot, "usd_cad_rate", None)
        if rate is not None:
            out["usd_cad_rate"] = float(rate)
        fx_map = getattr(snapshot, "fx_rates", None)
        if isinstance(fx_map, dict) and fx_map:
            out["fx_rates"] = {
                str(k).upper(): float(v) for k, v in fx_map.items() if float(v) > 0
            }
        price_book = getattr(broker, "last_prices", None) or {}
        rows = []
        for row in out.get("positions") or []:
            sym = row["symbol"]
            updated = dict(row)
            if sym in positions:
                updated["shares"] = float(positions[sym])
            if sym in price_book:
                updated["last_price"] = float(price_book[sym])
            rows.append(updated)
        # Include broker longs not yet in file state (still held after a drop).
        # Skip zero-share broker noise (flat symbols outside file state).
        known = {r["symbol"] for r in rows}
        for sym, shares in positions.items():
            qty = float(shares)
            if sym in known or qty <= 0:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "shares": qty,
                    "cash": 0.0,
                    "last_price": float(price_book[sym]) if sym in price_book else None,
                    "peak": None,
                    "trough": None,
                }
            )
        out["positions"] = sorted(rows, key=lambda r: r["symbol"])
        # Fresh 20-hour SMA for Positions "Next buy/sell" copy.
        symbols = [str(r.get("symbol")) for r in out["positions"] if r.get("symbol")]
        if symbols and hasattr(broker, "latest_hourly_closes"):
            try:
                from app.picker.trend_gate import sma

                _px, _bars, closes = broker.latest_hourly_closes(symbols, use_rth=True)
                sma_map: dict[str, float] = {}
                if isinstance(closes, dict):
                    for sym, series in closes.items():
                        if not isinstance(series, (list, tuple)):
                            continue
                        avg = sma([float(x) for x in series])
                        if avg is not None:
                            sma_map[str(sym).upper()] = round(float(avg), 4)
                if sma_map:
                    out["sma20_by_symbol"] = sma_map
            except Exception:  # noqa: BLE001 — marks still usable without SMA
                pass
        out["marks_source"] = "ibkr"
    except Exception as exc:  # noqa: BLE001 — dashboard must fail soft
        out["marks_source"] = "files"
        out["marks_error"] = str(exc)
    finally:
        if broker is not None and hasattr(broker, "ib") and hasattr(broker.ib, "disconnect"):
            try:
                broker.ib.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return out
