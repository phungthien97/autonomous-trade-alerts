"""Streamlit render helpers for the remote portfolio tabs (§13)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.live.control import ack_risk, disable_trading, enable_trading
from app.paths import LivePaths, PickerPaths, ROOT
from app.remote.health import build_health_strip
from app.remote.marks import dashboard_ib_client_id, overlay_ibkr_marks
from app.remote.money import cash_and_invested, live_money_snapshot, position_rows
from app.remote.status import load_live_status, load_paper_status, load_picker_status


def _gateway_health_log() -> Path | None:
    for candidate in (
        Path.home() / "ibc" / "logs" / "gateway-health.log",
        Path("/home/ubuntu/ibc/logs/gateway-health.log"),
    ):
        if candidate.is_file():
            return candidate
    env = os.environ.get("GATEWAY_HEALTH_LOG")
    if env:
        path = Path(env)
        if path.is_file():
            return path
    return None


def _try_ibkr_marks(status: dict[str, Any]) -> dict[str, Any]:
    def _factory():
        from app.broker.ibkr import IbkrBroker

        os.environ["IB_CLIENT_ID"] = str(dashboard_ib_client_id())
        return IbkrBroker(dry_run=True)

    return overlay_ibkr_marks(status, broker_factory=_factory)


def _fmt_num(value: Any, digits: int = 2) -> Any:
    if value is None or value == "":
        return "—"
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value: Any, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if signed:
        return f"{num:+.2f}%"
    return f"{num:.1f}%"


def _slim_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    """Keep columns that have at least one real value; format numbers."""
    if not rows:
        return []
    keep: list[str] = []
    for col in columns:
        for row in rows:
            val = row.get(col)
            if val is None or val == "" or val == "—":
                continue
            keep.append(col)
            break
    out = []
    for row in rows:
        slim: dict[str, Any] = {}
        for col in keep:
            val = row.get(col)
            if col in {"shares"}:
                slim[col] = _fmt_num(val, 4 if float(val or 0) % 1 else 2)
            elif col in {"weight_pct", "to_sell_pct", "to_buy_pct"}:
                slim[col] = _fmt_num(val, 1)
            elif col in {
                "last_price",
                "peak",
                "trough",
                "price",
                "buy_rise",
                "sell_drop",
                "value",
                "mkt_value",
                "cash",
            }:
                slim[col] = _fmt_num(val, 2)
            else:
                slim[col] = "—" if val is None else val
        out.append(slim)
    return out


def render_health_strip(st: Any, strip: dict[str, Any], *, marks_source: str | None = None) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Worker", "fresh" if strip["worker_fresh"] else "stale")
    c2.metric("Mode", strip["mode"])
    c3.metric("Trading", "ON" if strip["trading_on"] else "OFF")
    c4.metric("Risk", "OPEN" if strip["risk_open"] else "clear")
    bits = []
    if strip.get("stale_minutes") is not None:
        bits.append(f"{strip['stale_minutes']}m ago")
    if strip.get("gateway_ok") is True:
        bits.append("gateway OK")
    elif strip.get("gateway_ok") is False:
        bits.append("gateway FAIL")
    if strip.get("rth_ok") is False:
        bits.append("outside RTH")
    elif strip.get("rth_ok") is True:
        bits.append("RTH")
    if marks_source and marks_source != "files":
        bits.append(f"marks={marks_source}")
    if strip.get("price_source"):
        bits.append(str(strip["price_source"]))
    if bits:
        st.caption(" · ".join(bits))
    if strip.get("incident"):
        st.warning(f"Risk incident: {strip['incident']}")


def _render_money_hero(st: Any, money: dict[str, Any], status: dict[str, Any]) -> None:
    nav = money.get("nav")
    ret = money.get("bot_return_pct")
    day_delta = money.get("day_delta")
    day_pct = money.get("day_delta_pct")
    cash = money.get("cash")
    invested = money.get("invested")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NAV", _fmt_money(nav))
    c2.metric("Since start", _fmt_pct(ret) if ret is not None else "—")
    if day_delta is not None:
        delta_label = _fmt_money(day_delta)
        if day_pct is not None:
            c3.metric("Day Δ", delta_label, delta=_fmt_pct(day_pct))
        else:
            c3.metric("Day Δ", delta_label)
    else:
        c3.metric("Day Δ", "—")
    c4.metric("Cash / invested", f"{_fmt_money(cash)} / {_fmt_money(invested)}")

    bits: list[str] = []
    book = money.get("starting_cash")
    if book is not None:
        bits.append(f"book budget {_fmt_money(book)}")
    broker_cash = status.get("cash_usd")
    broker_eq = status.get("broker_equity_usd")
    if isinstance(broker_cash, (int, float)) and book is not None:
        if abs(float(broker_cash) - float(book)) > 1:
            bits.append(f"IBKR cash {_fmt_money(broker_cash)}")
    if isinstance(broker_eq, (int, float)):
        bits.append(f"IBKR equity {_fmt_money(broker_eq)}")
    last = status.get("last_cycle") or {}
    if isinstance(last, dict):
        if last.get("at_eastern"):
            bits.append(f"cycle {last['at_eastern']}")
        elif last.get("at_utc"):
            bits.append(f"cycle {last['at_utc']}")
        if last.get("price_source"):
            bits.append(str(last["price_source"]))
    if bits:
        st.caption(" · ".join(bits))


def _render_edge_strip(st: Any, edge: dict[str, Any], bot_return_pct: float | None) -> None:
    if edge.get("ok"):
        st.caption(
            f"Bot {_fmt_pct(edge.get('bot_return_pct'))} · "
            f"B&H {_fmt_pct(edge.get('bh_return_pct'))} · "
            f"edge {_fmt_pct(edge.get('edge_pct'))}"
        )
    elif bot_return_pct is not None:
        reason = edge.get("reason") or "B&H when prices available"
        st.caption(f"Bot {_fmt_pct(bot_return_pct)} · {reason}")


def render_live_tab(st: Any, project_root: Path | None = None) -> None:
    root = project_root or ROOT
    live_paths = LivePaths(project_root=root)
    picker_paths = PickerPaths(project_root=root)

    refresh = st.button("Refresh", type="primary", key="remote_live_refresh")
    status = load_live_status(live_paths.state_dir)
    if refresh:
        status = _try_ibkr_marks(status)
    picker = load_picker_status(picker_paths.state_dir)

    strip = build_health_strip(
        live_status=status,
        gateway_health_log=_gateway_health_log(),
    )
    render_health_strip(st, strip, marks_source=status.get("marks_source"))

    st.divider()
    money = live_money_snapshot(
        positions=status.get("positions") or [],
        total_cash=status.get("total_cash"),
        equity_path=live_paths.equity_path,
        symbols=list(status.get("symbols") or []),
        picker_active=picker.get("active") or [],
    )
    _render_money_hero(st, money, status)
    _render_edge_strip(st, money.get("edge") or {}, money.get("bot_return_pct"))

    holdings = _slim_rows(
        money.get("holdings") or [],
        ["symbol", "shares", "price", "value", "weight_pct", "to_sell_pct", "to_buy_pct", "flag"],
    )
    if holdings:
        st.dataframe(holdings, use_container_width=True, hide_index=True)
    else:
        st.info("Flat — no positions.")

    last = status.get("last_cycle") or {}
    decisions = last.get("decisions") if isinstance(last, dict) else None
    if isinstance(decisions, list) and decisions:
        st.subheader("Last cycle")
        rows = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            reason = d.get("signal_reason") or ""
            if isinstance(reason, str) and len(reason) > 48:
                reason = reason[:45] + "…"
            rows.append(
                {
                    "symbol": d.get("symbol"),
                    "signal": d.get("signal") or "—",
                    "plan": d.get("plan") or "—",
                    "action": d.get("action") or "—",
                    "reason": reason or None,
                }
            )
        st.dataframe(
            _slim_rows(rows, ["symbol", "signal", "plan", "action", "reason"]),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    b1, b2, b3 = st.columns(3)
    if b1.button("Disable trading", use_container_width=True, key="remote_disable"):
        disable_trading(live_paths)
        st.rerun()
    if b2.button("Enable trading", use_container_width=True, key="remote_enable"):
        enable_trading(live_paths)
        st.rerun()
    if b3.button("Ack risk", use_container_width=True, key="remote_ack"):
        ack_risk(live_paths)
        st.rerun()


def render_paper_tab(st: Any, version: str, project_root: Path | None = None) -> None:
    root = project_root or ROOT
    state_dir = root / ("state" if version == "v1" else "state_v2")
    if st.button("Refresh", type="primary", key=f"remote_paper_refresh_{version}"):
        st.rerun()
    status = load_paper_status(state_dir)
    if not status["exists"]:
        st.warning(f"No {state_dir.name}/ on this host.")
        return

    positions = status.get("positions") or []
    pv = status.get("portfolio_value")
    cash, invested = cash_and_invested(positions)
    nav = float(pv) if isinstance(pv, (int, float)) else (cash + invested)

    c1, c2, c3 = st.columns(3)
    c1.metric("NAV", _fmt_money(nav))
    c2.metric("Cash", _fmt_money(cash))
    c3.metric("Invested", _fmt_money(invested))
    st.caption("file-sim paper (not IBKR paper)")
    if status.get("last_run_at"):
        st.caption(f"Last worker run: {status['last_run_at']}")

    holdings = position_rows(positions, nav=nav)
    display = []
    for row in holdings:
        display.append(
            {
                "symbol": row.get("symbol"),
                "shares": row.get("shares"),
                "price": row.get("price"),
                "value": row.get("value"),
                "weight_pct": row.get("weight_pct"),
                "last_action": row.get("last_action"),
            }
        )
    slim = _slim_rows(display, ["symbol", "shares", "price", "value", "weight_pct", "last_action"])
    if slim:
        st.dataframe(slim, use_container_width=True, hide_index=True)
    else:
        st.info("No positions.")


def render_picker_tab(st: Any, project_root: Path | None = None) -> None:
    root = project_root or ROOT
    picker_paths = PickerPaths(project_root=root)
    if st.button("Refresh", type="primary", key="remote_picker_refresh"):
        st.rerun()
    status = load_picker_status(picker_paths.state_dir)

    latest = status.get("latest_run")
    if latest:
        st.subheader("Latest rank")
        st.write(
            f"**{latest.get('run_id')}** · "
            f"{'dry-run' if latest.get('dry_run') else 'live write'} · "
            f"{'aborted' if latest.get('aborted') else 'ok'}"
        )
        selected = latest.get("selected") or []
        st.write(", ".join(selected) if selected else "(none selected)")

    st.subheader("Active")
    active = status.get("active") or []
    if active:
        st.caption(f"run {status.get('active_run_id')} · applied {status.get('active_applied_at')}")
        st.caption("These sleeves drive Live buy/sell distances.")
        st.dataframe(
            _slim_rows(
                [
                    {
                        "symbol": a.get("symbol"),
                        "buy_rise": a.get("buy_rise"),
                        "sell_drop": a.get("sell_drop"),
                        "flag": (
                            "exit only"
                            if a.get("exit_only")
                            else ("awaiting buy" if a.get("awaiting_first_buy") else "active")
                        ),
                    }
                    for a in active
                ],
                ["symbol", "buy_rise", "sell_drop", "flag"],
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No active selection yet (waiting for Monday apply).")

    st.subheader("Pending")
    if status.get("pending_present"):
        st.write(", ".join(status.get("pending_symbols") or []) or "(empty list)")
        st.caption(f"apply after {status.get('pending_apply_after')}")
    else:
        st.caption("None (dry-run does not write pending).")
