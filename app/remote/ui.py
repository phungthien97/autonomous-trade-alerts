"""Streamlit render helpers for the remote portfolio tabs (§13)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.live.control import ack_risk, disable_trading, enable_trading
from app.paths import LivePaths, PickerPaths, ROOT
from app.remote.health import build_health_strip
from app.remote.marks import dashboard_ib_client_id, overlay_ibkr_marks
from app.remote.money import cash_and_invested, live_money_snapshot, position_rows
from app.remote.status import load_live_status, load_paper_status, load_picker_status

_ET = ZoneInfo("America/New_York")


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


def _fmt_frac_pct(value: Any, *, digits: int = 1) -> str:
    """Format a unit fraction (0.289 → +28.9%)."""
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value) * 100.0:+.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_trigger_pct(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_eastern(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        raw = str(iso).replace("Z", "+00:00")
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        local = moment.astimezone(_ET)
        return local.strftime("%a %b %d · %I:%M %p %Z").replace(" 0", " ")
    except ValueError:
        return str(iso)


def _tab_chrome(st: Any, caption: str, *, refresh_key: str) -> bool:
    """Shared caption + secondary Refresh row used by every tab."""
    top_l, top_r = st.columns([4, 1])
    with top_l:
        st.caption(caption)
    with top_r:
        return bool(st.button("Refresh", type="secondary", key=refresh_key))


def _show_table(st: Any, rows: list[dict[str, Any]], empty: str) -> None:
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info(empty)


def _holdings_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Title-case holdings rows shared by Live + Paper."""
    out: list[dict[str, Any]] = []
    for row in rows:
        shares = row.get("shares")
        try:
            share_digits = 4 if float(shares or 0) % 1 else 2
        except (TypeError, ValueError):
            share_digits = 2
        item: dict[str, Any] = {
            "Symbol": row.get("symbol") or "—",
            "Shares": _fmt_num(shares, share_digits),
            "Price": _fmt_money(row.get("price")),
            "Value": _fmt_money(row.get("value")),
            "Weight": _fmt_pct(row.get("weight_pct"), signed=False)
            if row.get("weight_pct") is not None
            else "—",
        }
        if row.get("to_sell_pct") is not None:
            item["To sell"] = _fmt_pct(row.get("to_sell_pct"))
        if row.get("to_buy_pct") is not None:
            item["To buy"] = _fmt_pct(row.get("to_buy_pct"))
        if row.get("flag"):
            item["Status"] = row.get("flag")
        if row.get("last_action"):
            item["Last action"] = row.get("last_action")
        out.append(item)
    # Drop columns that are entirely empty/dash across rows
    if not out:
        return out
    keep = [k for k in out[0] if any(r.get(k) not in (None, "", "—") for r in out)]
    return [{k: r.get(k, "—") for k in keep} for r in out]


def _picker_sleeve_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Human-readable sleeve rows for the Picker tab."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        out.append(
            {
                "#": i,
                "Symbol": row.get("symbol") or "—",
                "Company": row.get("name") or "—",
                "Sector": row.get("sector") or "—",
                "Strategy profit": _fmt_frac_pct(row.get("strategy_return")),
                "Beat B&H by": _fmt_frac_pct(row.get("edge")),
                "Buy trigger": f"+{_fmt_trigger_pct(row.get('buy_rise'))} off trough"
                if row.get("buy_rise") is not None
                else "—",
                "Sell trigger": f"−{_fmt_trigger_pct(row.get('sell_drop'))} off peak"
                if row.get("sell_drop") is not None
                else "—",
            }
        )
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
            c3.metric("Day P&L", delta_label, delta=_fmt_pct(day_pct))
        else:
            c3.metric("Day P&L", delta_label)
    else:
        c3.metric("Day P&L", "—")
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
            bits.append(f"cycle {_fmt_eastern(str(last['at_utc']))}")
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

    refresh = _tab_chrome(
        st,
        "IBKR paper / live book · health, money, and safe controls",
        refresh_key="remote_live_refresh",
    )
    status = load_live_status(live_paths.state_dir)
    if refresh:
        status = _try_ibkr_marks(status)
    picker = load_picker_status(picker_paths.state_dir)

    st.subheader("Health")
    strip = build_health_strip(
        live_status=status,
        gateway_health_log=_gateway_health_log(),
    )
    render_health_strip(st, strip, marks_source=status.get("marks_source"))

    st.subheader("Portfolio")
    money = live_money_snapshot(
        positions=status.get("positions") or [],
        total_cash=status.get("total_cash"),
        equity_path=live_paths.equity_path,
        symbols=list(status.get("symbols") or []),
        picker_active=picker.get("active") or [],
    )
    _render_money_hero(st, money, status)
    _render_edge_strip(st, money.get("edge") or {}, money.get("bot_return_pct"))
    _show_table(
        st,
        _holdings_table(money.get("holdings") or []),
        "Flat — no positions yet.",
    )

    last = status.get("last_cycle") or {}
    decisions = last.get("decisions") if isinstance(last, dict) else None
    st.subheader("Last cycle")
    if isinstance(decisions, list) and decisions:
        rows = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            reason = d.get("signal_reason") or ""
            if isinstance(reason, str) and len(reason) > 64:
                reason = reason[:61] + "…"
            rows.append(
                {
                    "Symbol": d.get("symbol") or "—",
                    "Signal": d.get("signal") or "—",
                    "Plan": d.get("plan") or "—",
                    "Action": d.get("action") or "—",
                    "Reason": reason or "—",
                }
            )
        _show_table(st, rows, "No decisions this cycle.")
    else:
        st.caption("No cycle decisions recorded yet.")

    st.subheader("Controls")
    st.caption("Safe ops only — disable / enable trading and acknowledge risk incidents.")
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
    label = "V1" if version == "v1" else "V2"
    state_dir = root / ("state" if version == "v1" else "state_v2")
    _tab_chrome(
        st,
        f"Paper {label} · file-sim experiment (not IBKR paper)",
        refresh_key=f"remote_paper_refresh_{version}",
    )
    status = load_paper_status(state_dir)
    if not status["exists"]:
        st.warning(f"No `{state_dir.name}/` on this host yet.")
        return

    positions = status.get("positions") or []
    pv = status.get("portfolio_value")
    cash, invested = cash_and_invested(positions)
    nav = float(pv) if isinstance(pv, (int, float)) else (cash + invested)

    st.subheader("Portfolio")
    c1, c2, c3 = st.columns(3)
    c1.metric("NAV", _fmt_money(nav))
    c2.metric("Cash", _fmt_money(cash))
    c3.metric("Invested", _fmt_money(invested))
    if status.get("last_run_at"):
        st.caption(f"Last worker run · {_fmt_eastern(str(status['last_run_at']))}")
    else:
        st.caption("Last worker run · —")

    holdings = position_rows(positions, nav=nav)
    _show_table(st, _holdings_table(holdings), "No positions.")


def render_picker_tab(st: Any, project_root: Path | None = None) -> None:
    root = project_root or ROOT
    picker_paths = PickerPaths(project_root=root)
    if _tab_chrome(
        st,
        "S&P ranking · beat buy-&-hold and made money · rank by strategy profit",
        refresh_key="remote_picker_refresh",
    ):
        st.rerun()

    status = load_picker_status(picker_paths.state_dir)
    latest = status.get("latest_run") or {}
    pending_rows = list(status.get("pending_rows") or [])
    apply_label = _fmt_eastern(status.get("pending_apply_after"))

    st.subheader("Queued for Monday")
    if status.get("pending_present") and pending_rows:
        st.success(f"Applies **{apply_label}** · first live-worker cycle after the open")
        _show_table(st, _picker_sleeve_table(pending_rows), "(none)")
        st.caption(
            "Strategy profit = after-fee return on the score window. "
            "Beat B&H = how much better than buy-and-hold. "
            "No action needed unless you want to cancel before apply."
        )
    elif status.get("pending_present"):
        syms = status.get("pending_symbols") or []
        st.success(f"Applies **{apply_label}**")
        st.write(", ".join(syms) if syms else "(empty — all cash)")
    else:
        st.info("Nothing queued. Weekend ranking will write pending when it next runs.")

    st.subheader("Live sleeves now")
    active = status.get("active") or []
    if active:
        st.caption(
            f"Run `{status.get('active_run_id')}` · applied "
            f"{_fmt_eastern(status.get('active_applied_at'))}"
        )
        _show_table(
            st,
            [
                {
                    "Symbol": a.get("symbol") or "—",
                    "Buy trigger": f"+{_fmt_trigger_pct(a.get('buy_rise'))} off trough"
                    if a.get("buy_rise") is not None
                    else "—",
                    "Sell trigger": f"−{_fmt_trigger_pct(a.get('sell_drop'))} off peak"
                    if a.get("sell_drop") is not None
                    else "—",
                    "Status": (
                        "Exit only"
                        if a.get("exit_only")
                        else ("Awaiting first buy" if a.get("awaiting_first_buy") else "Active")
                    ),
                }
                for a in active
            ],
            "No active sleeves.",
        )
    else:
        st.info("No active sleeves yet — waiting for the first Monday apply.")

    st.subheader("Last ranking run")
    if latest:
        mode = "dry run" if latest.get("dry_run") else "live write"
        outcome = "aborted" if latest.get("aborted") else "ok"
        st.write(f"**{latest.get('run_id')}** · {mode} · {outcome}")
        latest_syms = [str(s) for s in (latest.get("selected") or [])]
        pending_syms = [str(r.get("symbol")) for r in pending_rows if r.get("symbol")]
        if latest_syms and latest_syms != pending_syms:
            rows = latest.get("selected_rows") or [{"symbol": s} for s in latest_syms]
            _show_table(st, _picker_sleeve_table(rows), "(none)")
        elif latest_syms:
            st.caption("Same sleeve list as queued above.")
        else:
            st.caption("No symbols selected in that run.")
    else:
        st.caption("No ranking reports on disk yet.")
