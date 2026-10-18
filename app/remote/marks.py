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
        # Include broker-only symbols not yet in file state
        known = {r["symbol"] for r in rows}
        for sym, shares in positions.items():
            if sym not in known:
                rows.append(
                    {
                        "symbol": sym,
                        "shares": float(shares),
                        "cash": 0.0,
                        "last_price": float(price_book[sym]) if sym in price_book else None,
                        "peak": None,
                        "trough": None,
                    }
                )
        out["positions"] = sorted(rows, key=lambda r: r["symbol"])
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
