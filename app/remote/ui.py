"""Streamlit render helpers for the remote portfolio tabs (§13)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.live.account_nav import load_daily_nav
from app.live.control import (
    DAILY_ORDER_CAP_MAX,
    DAILY_ORDER_CAP_MIN,
    ack_risk,
    disable_trading,
    enable_trading,
    set_daily_order_cap,
)
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
    clicked = False
    with st.container():
        top_l, top_r = st.columns([4, 1])
        with top_l:
            st.caption(caption)
        with top_r:
            clicked = bool(st.button("Refresh", type="secondary", key=refresh_key))
    return clicked


def _show_table(
    st: Any,
    rows: list[dict[str, Any]],
    empty: str,
    *,
    wrap_cols: tuple[str, ...] = (),
) -> None:
    if not rows:
        st.info(empty)
        return
    # All-string cells + explicit column order keep Arrow/Streamlit from
    # collapsing to a single narrow Symbol column on some hosts.
    cols = list(rows[0].keys())
    safe = [{k: ("" if row.get(k) is None else str(row.get(k))) for k in cols} for row in rows]
    column_config = None
    if wrap_cols:
        try:
            column_config = {
                name: st.column_config.TextColumn(name, width="large")
                for name in wrap_cols
                if name in cols
            }
        except Exception:  # noqa: BLE001 — older Streamlit
            column_config = None
    try:
        import pandas as pd

        frame = pd.DataFrame(safe, columns=cols)
        kwargs: dict[str, Any] = {"use_container_width": True, "hide_index": True}
        if column_config:
            kwargs["column_config"] = column_config
        st.dataframe(frame, **kwargs)
    except Exception:  # noqa: BLE001
        st.dataframe(safe, use_container_width=True, hide_index=True)


def _fmt_shares(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num == int(num):
        return f"{int(num)}"
    return f"{num:.4f}".rstrip("0").rstrip(".")


def _fmt_whole_shares(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _account_next_plan(row: dict[str, Any]) -> str:
    """Dollar trigger + planned whole-share size for the next action."""
    shares = float(row.get("shares") or 0.0)
    reason = str(row.get("reason") or "")
    if shares > 0:
        bits: list[str] = []
        if row.get("sell_trigger") is not None:
            bits.append(f"Sell at {_fmt_money(row.get('sell_trigger'))}")
        bits.append(f"all {_fmt_whole_shares(shares)} sh")
        return " · ".join(bits)
    planned = row.get("planned_shares")
    budget = row.get("buy_budget")
    bits = []
    if isinstance(planned, int) and planned > 0:
        bits.append(f"Buy ~{_fmt_whole_shares(planned)} sh")
        if budget is not None:
            bits.append(_fmt_money(budget))
    elif budget is not None:
        bits.append(f"can't afford 1 sh ({_fmt_money(budget)})")
    if "20-hour average" in reason:
        bits.append("after 20-hour average clears")
    elif row.get("buy_trigger") is not None:
        bits.append(f"when ≥ {_fmt_money(row.get('buy_trigger'))}")
    return " · ".join(bits) if bits else "—"


def _account_holdings_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One easy table for whole-account mode: position + levels + why."""
    out: list[dict[str, Any]] = []
    for row in rows:
        orders = row.get("orders_today")
        try:
            orders_txt = str(int(orders)) if orders is not None else "0"
        except (TypeError, ValueError):
            orders_txt = "0"
        out.append(
            {
                "Symbol": row.get("symbol") or "—",
                "Shares": _fmt_shares(row.get("shares")),
                "Price": _fmt_money(row.get("price")),
                "Value": _fmt_money(
                    row.get("stock_value") if row.get("stock_value") is not None else row.get("mkt_value")
                ),
                "Orders today": orders_txt,
                "Low": _fmt_money(row.get("trough")) if row.get("trough") is not None else "—",
                "High": _fmt_money(row.get("peak")) if row.get("peak") is not None else "—",
                "Next buy/sell": _account_next_plan(row),
                "Why": str(row.get("reason") or "—"),
            }
        )
    return out


def _holdings_table(
    rows: list[dict[str, Any]],
    *,
    live_book: bool = False,
    use_account_cash: bool = False,
) -> list[dict[str, Any]]:
    """Title-case holdings rows. Account mode hides misleading sleeve cash."""
    if live_book and use_account_cash:
        return _account_holdings_table(rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        if live_book:
            item = {
                "Symbol": row.get("symbol") or "—",
                "Shares": _fmt_shares(row.get("shares")),
                "Price": _fmt_money(row.get("price")),
                "Stock value": _fmt_money(row.get("stock_value") if row.get("stock_value") is not None else row.get("mkt_value")),
                "Sleeve cash": _fmt_money(
                    row.get("sleeve_cash") if row.get("sleeve_cash") is not None else row.get("cash")
                ),
                "Sleeve total": _fmt_money(
                    row.get("sleeve_total") if row.get("sleeve_total") is not None else row.get("value")
                ),
            }
            if row.get("flag"):
                item["Status"] = str(row.get("flag"))
            if row.get("to_sell_pct") is not None:
                item["To sell"] = _fmt_pct(row.get("to_sell_pct"))
            if row.get("to_buy_pct") is not None:
                item["To buy"] = _fmt_pct(row.get("to_buy_pct"))
        else:
            item = {
                "Symbol": row.get("symbol") or "—",
                "Shares": _fmt_shares(row.get("shares")),
                "Price": _fmt_money(row.get("price")),
                "Value": _fmt_money(row.get("value")),
                "Weight": _fmt_pct(row.get("weight_pct"), signed=False)
                if row.get("weight_pct") is not None
                else "—",
            }
            if row.get("flag"):
                item["Status"] = str(row.get("flag"))
            if row.get("last_action"):
                item["Last action"] = str(row.get("last_action"))
            if row.get("to_sell_pct") is not None:
                item["To sell"] = _fmt_pct(row.get("to_sell_pct"))
            if row.get("to_buy_pct") is not None:
                item["To buy"] = _fmt_pct(row.get("to_buy_pct"))
        out.append(item)
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


def _mode_label(mode: str) -> str:
    labels = {
        "broker_paper": "Paper (IBKR)",
        "broker_live": "Live (IBKR)",
        "live_dry_run": "Dry run",
        "memory": "Memory sim",
    }
    return labels.get(str(mode), str(mode))


def _price_source_label(source: str | None) -> str | None:
    if not source:
        return None
    labels = {
        "ibkr_rth_hourly": "Prices: IBKR hourly (regular hours)",
        "ibkr": "Prices: IBKR",
        "files": "Prices: saved files",
    }
    return labels.get(str(source), f"Prices: {source}")


def render_health_strip(
    st: Any,
    strip: dict[str, Any],
    *,
    marks_source: str | None = None,
) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Bot run",
        "Up to date" if strip["worker_fresh"] else "Stale",
        help=(
            "Whether the trading bot finished a cycle recently. "
            "Up to date = last run within ~15 minutes. "
            "Stale = no recent cycle — check the host or broker gateway."
        ),
    )
    c2.metric(
        "Account mode",
        _mode_label(str(strip.get("mode") or "unknown")),
        help=(
            "Where orders go. "
            "Paper (IBKR) = simulated money, no real fills. "
            "Live (IBKR) = real money. "
            "Dry run / Memory = local simulation only."
        ),
    )
    c3.metric(
        "Orders",
        "Enabled" if strip["trading_on"] else "Paused",
        help=(
            "Master switch for placing buys/sells. "
            "Enabled = bot may send orders when signals fire in market hours. "
            "Paused = bot still runs and shows plans, but will not send orders."
        ),
    )
    c4.metric(
        "Risk stop",
        "Needs ack" if strip["risk_open"] else "OK",
        help=(
            "Safety latch after alerts (disconnects, caps, manual stops). "
            "OK = no open incident. "
            "Needs ack = trading may be blocked until you acknowledge risk."
        ),
    )
    bits = []
    if strip.get("stale_minutes") is not None:
        bits.append(f"Last cycle {strip['stale_minutes']}m ago")
    if strip.get("gateway_ok") is True:
        bits.append("Broker link OK")
    elif strip.get("gateway_ok") is False:
        bits.append("Broker link FAIL")
    if strip.get("rth_ok") is False:
        bits.append("Outside market hours (no new fills)")
    elif strip.get("rth_ok") is True:
        bits.append("Regular market hours")
    if marks_source and marks_source != "files":
        bits.append("Live balances from IBKR")
    elif marks_source == "files":
        bits.append("Balances from saved files")
    price_bit = _price_source_label(strip.get("price_source"))
    if price_bit:
        bits.append(price_bit)
    if bits:
        st.caption(" · ".join(bits))
    if strip.get("incident"):
        st.warning(f"Risk incident: {strip['incident']}")


def _render_money_hero(st: Any, money: dict[str, Any], status: dict[str, Any]) -> None:
    book = money.get("book_capital")
    if book is None:
        book = money.get("starting_cash")
    invested = money.get("invested")
    cash = money.get("cash")
    nav = money.get("nav")
    ret = money.get("bot_return_pct")
    day_delta = money.get("day_delta")
    day_pct = money.get("day_delta_pct")

    if money.get("status_line"):
        st.caption(str(money["status_line"]))

    use_account = bool(status.get("use_account_cash", True)) or bool(money.get("use_account_cash"))
    if use_account:
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Account total",
            _fmt_money(nav if nav is not None else book),
            help=(
                "Full broker account value (base currency). "
                "Includes cash, stock positions, and accrued interest. "
                "Can be higher than Cash even with nothing in stock."
            ),
        )
        c2.metric(
            "In stocks",
            _fmt_money(invested),
            help=(
                "Market value of stock/ETF holdings only (broker position value). "
                "Zero means flat — accrued interest is not counted here."
            ),
        )
        c3.metric(
            "Cash",
            _fmt_money(cash),
            help=(
                "Broker statement cash balance. "
                "Does not include accrued interest or stock positions."
            ),
        )
        accrued = money.get("accrued_cash")
        if isinstance(accrued, (int, float)) and abs(float(accrued)) >= 0.01:
            st.caption(
                f"Accrued interest {_fmt_money(float(accrued))} "
                f"(part of account total; not stock holdings)"
            )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Book capital",
            _fmt_money(book),
            help="Starting cash allocated to this bot book.",
        )
        c2.metric(
            "In stocks",
            _fmt_money(invested),
            help="Mark-to-market value of shares held in the bot book.",
        )
        c3.metric(
            "In cash",
            _fmt_money(cash),
            help="Cash left in the bot book (not yet in shares).",
        )
        c4.metric(
            "Book total",
            _fmt_money(nav),
            help="In stocks + In cash for this bot book.",
        )

    if use_account:
        r1, r2 = st.columns(2)
        spend = money.get("available_funds")
        r1.metric(
            "Can deploy now",
            _fmt_money(spend) if spend is not None else "—",
            help=(
                "Cash the bot may spend on new buys (never-borrow). "
                "While you hold stock this is capped at Cash — not IBKR "
                "AvailableFunds, which can include a loan against those shares. "
                "When flat it may match AvailableFunds (same-day unsettled credit). "
                "Buy sizing uses this ÷ flat names."
            ),
        )
        day_help = (
            "Change in full account value vs the prior Eastern calendar day "
            "(from the daily equity log). Includes open positions, cash, "
            "realized trades today, and accrued interest — not share marks alone."
        )
        if day_delta is not None:
            delta_label = _fmt_money(day_delta)
            if day_pct is not None:
                r2.metric("Day P&L", delta_label, delta=_fmt_pct(day_pct), help=day_help)
            else:
                r2.metric("Day P&L", delta_label, help=day_help)
        else:
            r2.metric("Day P&L", "—", help=day_help)
    else:
        r1, r2 = st.columns(2)
        r1.metric(
            "Since start",
            _fmt_pct(ret) if ret is not None else "—",
            help="Bot book return versus starting capital.",
        )
        if day_delta is not None:
            delta_label = _fmt_money(day_delta)
            if day_pct is not None:
                r2.metric(
                    "Day P&L",
                    delta_label,
                    delta=_fmt_pct(day_pct),
                    help="Change in book value since the prior trading day.",
                )
            else:
                r2.metric(
                    "Day P&L",
                    delta_label,
                    help="Change in book value since the prior trading day.",
                )
        else:
            r2.metric(
                "Day P&L",
                "—",
                help="Change in book value since the prior trading day.",
            )

    bits: list[str] = []
    broker_cash = status.get("cash_usd")
    broker_eq = status.get("broker_equity_usd")
    if use_account:
        bits.append("account totals converted to USD when IBKR ExchangeRate is present")
        bits.append("position prices/values are USD")
        bits.append("buy size uses Can deploy now ÷ flat names (never-borrow)")
    elif isinstance(broker_cash, (int, float)) and book is not None:
        if abs(float(broker_cash) - float(book)) > 1:
            bits.append(f"IBKR paper account cash {_fmt_money(broker_cash)} (not bot book)")
    if isinstance(broker_eq, (int, float)) and not use_account:
        bits.append(f"IBKR equity {_fmt_money(broker_eq)}")
    last = status.get("last_cycle") or {}
    if isinstance(last, dict):
        if last.get("at_eastern"):
            bits.append(f"cycle {last['at_eastern']}")
        elif last.get("at_utc"):
            bits.append(f"cycle {_fmt_eastern(str(last['at_utc']))}")
        if last.get("price_source"):
            bits.append(str(last["price_source"]))
    dropped = money.get("orphan_dropped") or 0
    if dropped:
        bits.append(f"hid {dropped} orphan sleeve(s)")
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


def _render_performance_chart(st: Any, nav_path: Path) -> None:
    """Day-to-day account equity under the positions table."""
    st.subheader("Performance")
    points = load_daily_nav(nav_path)
    if not points:
        st.caption("Day-to-day equity chart appears after the worker logs account value.")
        return
    first = points[0]
    last = points[-1]
    since = None
    if first["equity"] and first["equity"] > 0:
        since = ((float(last["equity"]) - float(first["equity"])) / float(first["equity"])) * 100.0
    bits = [
        f"{len(points)} day(s)",
        f"{first['date']} → {last['date']}",
        f"latest {_fmt_money(last['equity'])}",
    ]
    if since is not None and len(points) >= 2:
        bits.append(f"since first log {_fmt_pct(since)}")
    st.caption(" · ".join(bits) + " · one point per Eastern calendar day (IBKR account equity)")

    if len(points) == 1:
        st.info(f"Logged {_fmt_money(points[0]['equity'])} on {points[0]['date']}. Chart needs 2+ days.")
        return

    try:
        import pandas as pd
    except ImportError:
        st.caption("pandas required for chart")
        return

    frame = pd.DataFrame(points)
    chart = frame.set_index("date")[["equity"]].rename(columns={"equity": "Account equity"})
    st.line_chart(chart, height=280)

    recent = list(reversed(points[-14:]))
    rows = []
    for row in recent:
        ch = row.get("day_change")
        pct = row.get("day_change_pct")
        rows.append(
            {
                "Date": row["date"],
                "Equity": _fmt_money(row["equity"]),
                "Day change": _fmt_money(ch) if ch is not None else "—",
                "Day %": _fmt_pct(pct) if pct is not None else "—",
            }
        )
    _show_table(st, rows, "No daily points yet.")


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
    render_health_strip(
        st,
        strip,
        marks_source=status.get("marks_source"),
    )

    st.subheader("Portfolio")
    use_account = bool(status.get("use_account_cash", True))
    last_preview = status.get("last_cycle") or {}
    cycle_reasons: dict[str, str] = {}
    if isinstance(last_preview, dict):
        for d in last_preview.get("decisions") or []:
            if isinstance(d, dict) and d.get("symbol") and d.get("signal_reason"):
                cycle_reasons[str(d["symbol"])] = str(d["signal_reason"])
    money = live_money_snapshot(
        positions=status.get("positions") or [],
        total_cash=status.get("total_cash"),
        equity_path=live_paths.equity_path,
        account_nav_path=live_paths.account_nav_path,
        symbols=list(status.get("symbols") or []),
        picker_active=picker.get("active") or [],
        use_account_cash=use_account,
        broker_cash=status.get("cash_usd") if isinstance(status.get("cash_usd"), (int, float)) else None,
        broker_equity=status.get("broker_equity_usd")
        if isinstance(status.get("broker_equity_usd"), (int, float))
        else status.get("total_cash"),
        available_funds=status.get("available_funds_usd")
        if isinstance(status.get("available_funds_usd"), (int, float))
        else None,
        broker_stock_value=status.get("gross_position_value_usd")
        if isinstance(status.get("gross_position_value_usd"), (int, float))
        else None,
        broker_accrued_cash=status.get("accrued_cash_usd")
        if isinstance(status.get("accrued_cash_usd"), (int, float))
        else None,
        cycle_reasons=cycle_reasons,
        orders_today_by_symbol=status.get("orders_today_by_symbol")
        if isinstance(status.get("orders_today_by_symbol"), dict)
        else None,
    )
    _render_money_hero(st, money, status)
    _render_edge_strip(st, money.get("edge") or {}, money.get("bot_return_pct"))

    last = status.get("last_cycle") or {}
    decisions = last.get("decisions") if isinstance(last, dict) else None
    when = None
    if isinstance(last, dict):
        when = last.get("at_eastern") or (
            _fmt_eastern(str(last["at_utc"])) if last.get("at_utc") else None
        )

    if use_account:
        st.subheader("Positions")
        cap = int(status.get("daily_order_cap") or 5)
        st.caption(
            f"Orders today column = broker submits for that symbol today "
            f"(limit **{cap} per symbol**, adjustable under Controls). "
            "Low / High = recent trough & peak · "
            "Next buy/sell ≈ whole shares from splitting available cash across flat names "
            "(size shrinks if another name buys first)."
        )
        _show_table(
            st,
            _holdings_table(
                money.get("holdings") or [],
                live_book=True,
                use_account_cash=True,
            ),
            "No active sleeves in the book.",
            wrap_cols=("Why", "Next buy/sell"),
        )
        actions = last.get("actions") if isinstance(last, dict) else None
        action_txt = ", ".join(str(a) for a in actions) if actions else "no orders"
        if when:
            st.caption(f"Last worker run · {when} · {action_txt}")
        elif not decisions:
            st.caption("No cycle decisions recorded yet.")
        _render_performance_chart(st, live_paths.account_nav_path)
    else:
        st.subheader("Portfolio holdings")
        _show_table(
            st,
            _holdings_table(
                money.get("holdings") or [],
                live_book=True,
                use_account_cash=False,
            ),
            "No active sleeves in the book.",
        )
        st.subheader("Last cycle")
        if when:
            st.caption(f"Worker ran · {when}")
        if isinstance(decisions, list) and decisions:
            rows = []
            for d in decisions:
                if not isinstance(d, dict):
                    continue
                reason = d.get("signal_reason") or ""
                rows.append(
                    {
                        "Symbol": d.get("symbol") or "—",
                        "Signal": d.get("signal") or "—",
                        "Plan": d.get("plan") or "—",
                        "Action": d.get("action") or "—",
                        "Reason": reason or "—",
                    }
                )
            _show_table(st, rows, "No decisions this cycle.", wrap_cols=("Reason", "Plan"))
        else:
            st.caption("No cycle decisions recorded yet.")
        _render_performance_chart(st, live_paths.account_nav_path)

    st.subheader("Controls")
    st.caption(
        "Safe ops only — pause/resume orders, acknowledge risk, adjust per-symbol daily order cap."
    )
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

    current_cap = int(status.get("daily_order_cap") or 5)
    by_sym = status.get("orders_today_by_symbol") if isinstance(status.get("orders_today_by_symbol"), dict) else {}
    busiest = 0
    for v in by_sym.values():
        try:
            busiest = max(busiest, int(v or 0))
        except (TypeError, ValueError):
            continue
    left = max(0, current_cap - busiest)
    st.markdown("**Change per-symbol daily order limit**")
    st.caption(
        f"Each ticker may submit up to **{current_cap}** broker orders per Eastern day. "
        f"Busiest symbol today: **{busiest}** used · **{left}** left on that name. "
        "Counts are in the Positions table above. "
        "Raising this does not clear a risk stop — use Ack risk if blocked. "
        "One email when a symbol first hits the limit."
    )
    cap_col, btn_col = st.columns([2, 1])
    new_cap = cap_col.number_input(
        "Set new per-symbol limit",
        min_value=DAILY_ORDER_CAP_MIN,
        max_value=DAILY_ORDER_CAP_MAX,
        value=min(max(current_cap, DAILY_ORDER_CAP_MIN), DAILY_ORDER_CAP_MAX),
        step=1,
        key="remote_daily_order_cap",
        help=(
            f"Maximum broker order submits per symbol per Eastern day. "
            f"You can set {DAILY_ORDER_CAP_MIN}–{DAILY_ORDER_CAP_MAX}."
        ),
    )
    if btn_col.button("Save cap", use_container_width=True, key="remote_save_order_cap"):
        try:
            written = set_daily_order_cap(live_paths, int(new_cap))
            st.success(f"Per-symbol daily order cap set to {written}.")
            st.rerun()
        except (ValueError, FileNotFoundError) as exc:
            st.error(str(exc))


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
