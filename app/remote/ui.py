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
    TRADING_BUDGET_USD_MAX,
    ack_risk,
    disable_trading,
    enable_trading,
    execute_rebalance_to_equal,
    execute_reduce_to_budget,
    preview_rebalance_from_broker,
    preview_reduce_to_budget,
    set_daily_order_cap,
    set_trading_budget_usd,
)
from app.live.session import is_us_equity_rth, next_rth_open
from app.picker.active import load_active
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


def _fmt_money(value: Any, *, currency: str | None = None) -> str:
    if value is None:
        return "—"
    try:
        text = f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"
    if currency:
        return f"{text} {currency}"
    return text


def _fx_rates_from_status(
    *,
    fx_rates: dict[str, float] | None = None,
    usd_cad_rate: float | None = None,
    account_currency: str | None = None,
) -> dict[str, float] | None:
    """Build a ledger FX map for display conversion."""
    if isinstance(fx_rates, dict) and fx_rates:
        return {str(k).upper(): float(v) for k, v in fx_rates.items() if float(v) > 0}
    acct = str(account_currency or "").upper()
    if usd_cad_rate is not None and float(usd_cad_rate) > 0 and acct in {"CAD", "BASE", ""}:
        return {"USD": float(usd_cad_rate), "BASE": 1.0, "CAD": 1.0}
    return None


def _fx_convert(
    value: Any,
    *,
    from_currency: str,
    to_currency: str,
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
    account_currency: str | None = None,
) -> float | None:
    """Convert amount using IBKR ledger FX map (BASE units per currency)."""
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    src = str(from_currency or "").upper()
    dst = str(to_currency or "").upper()
    if not src or not dst or src == dst:
        return amount
    from app.account_snapshot import convert_amount

    rates = _fx_rates_from_status(
        fx_rates=fx_rates,
        usd_cad_rate=usd_cad_rate,
        account_currency=account_currency or from_currency,
    )
    if not rates:
        return None
    converted = convert_amount(
        amount,
        from_currency=src,
        to_currency=dst,
        fx_rates=rates,
        account_currency=account_currency or src,
    )
    # convert_amount returns 0 on missing rate; treat that as failed conversion
    # only when the source amount was non-zero.
    if converted == 0.0 and amount != 0.0 and src != dst:
        return None
    return converted


def _fmt_fx(
    value: Any,
    *,
    from_currency: str,
    display_currency: str,
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
    account_currency: str | None = None,
) -> str:
    """Format ``value`` in ``display_currency``, converting via IBKR FX when needed."""
    src = str(from_currency or "USD").upper()
    dst = str(display_currency or src).upper()
    converted = _fx_convert(
        value,
        from_currency=src,
        to_currency=dst,
        usd_cad_rate=usd_cad_rate,
        fx_rates=fx_rates,
        account_currency=account_currency or src,
    )
    if converted is None:
        return _fmt_money(value, currency=src)
    return _fmt_money(converted, currency=dst)


def _display_currency_toggle(
    st: Any,
    *,
    account_currency: str,
    usd_cad_rate: float | None,
    fx_rates: dict[str, float] | None = None,
    key: str = "live_display_currency",
) -> str:
    """Account-currency / USD switch for money displays. Defaults to account ccy."""
    acct = str(account_currency or "USD").upper()
    if acct in {"BASE", ""}:
        acct = "CAD"
    rates = _fx_rates_from_status(
        fx_rates=fx_rates,
        usd_cad_rate=usd_cad_rate,
        account_currency=acct,
    )
    can_toggle = bool(rates and rates.get("USD") and acct != "USD")
    if not can_toggle:
        return acct
    options = [acct, "USD"]
    if key not in st.session_state:
        st.session_state[key] = acct
    elif st.session_state[key] not in options:
        st.session_state[key] = acct
    usd_rate = float(rates["USD"])
    choice = st.radio(
        "Show amounts in",
        options,
        horizontal=True,
        key=key,
        help=f"Convert with IBKR FX ({usd_rate:.4f} {acct} per 1 USD).",
    )
    return str(choice)


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


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _wrap_cell_html(text: str) -> str:
    """Turn plan/reason clauses into HTML line breaks (dataframe cannot wrap)."""
    raw = str(text or "").strip()
    if not raw or raw == "—":
        return _html_escape(raw or "—")
    parts = [p.strip() for p in raw.replace(" · ", "\n").split("\n") if p.strip()]
    return "<br/>".join(_html_escape(p) for p in parts)


def _show_html_table(
    st: Any,
    rows: list[dict[str, Any]],
    *,
    wrap_cols: tuple[str, ...] = (),
) -> None:
    """HTML table so long Next buy/sell / Why text actually wraps."""
    cols = list(rows[0].keys())
    wrap_set = {c for c in wrap_cols if c in cols}
    # Compact numeric-ish cols stay narrow; wrap cols get the remaining width.
    narrow = {
        "Symbol",
        "Shares",
        "Price",
        "Value",
        "Orders today",
        "Low",
        "High",
        "Side",
    }
    head_cells: list[str] = []
    for c in cols:
        style = "text-align:left;padding:0.45rem 0.55rem;border-bottom:1px solid #ddd;"
        if c in wrap_set:
            style += "min-width:14rem;width:28%;"
        elif c in narrow:
            style += "white-space:nowrap;"
        head_cells.append(f'<th style="{style}">{_html_escape(c)}</th>')
    body_rows: list[str] = []
    for row in rows:
        tds: list[str] = []
        for c in cols:
            val = "" if row.get(c) is None else str(row.get(c))
            if c in wrap_set:
                inner = _wrap_cell_html(val)
                cell_style = (
                    "text-align:left;padding:0.45rem 0.55rem;border-bottom:1px solid #eee;"
                    "white-space:normal;word-break:break-word;line-height:1.35;vertical-align:top;"
                )
            else:
                inner = _html_escape(val)
                cell_style = (
                    "text-align:left;padding:0.45rem 0.55rem;border-bottom:1px solid #eee;"
                    "white-space:nowrap;vertical-align:top;"
                )
            tds.append(f'<td style="{cell_style}">{inner}</td>')
        body_rows.append("<tr>" + "".join(tds) + "</tr>")
    html = (
        '<div style="width:100%;overflow-x:auto;">'
        '<table style="width:100%;border-collapse:collapse;font-size:0.92rem;">'
        "<thead><tr>"
        + "".join(head_cells)
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


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
    # Streamlit st.dataframe truncates long cells and will not wrap — use HTML
    # whenever the caller asks for wrap columns (positions Next buy/sell / Why).
    if wrap_cols:
        _show_html_table(st, rows, wrap_cols=wrap_cols)
        return
    cols = list(rows[0].keys())
    safe = [{k: ("" if row.get(k) is None else str(row.get(k))) for k in cols} for row in rows]
    try:
        import pandas as pd

        frame = pd.DataFrame(safe, columns=cols)
        st.dataframe(frame, use_container_width=True, hide_index=True)
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


def _account_next_plan(
    row: dict[str, Any],
    *,
    native_currency: str = "USD",
    display_currency: str = "USD",
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
    account_currency: str | None = None,
) -> str:
    """Dollar trigger + planned whole-share size for the next action."""
    shares = float(row.get("shares") or 0.0)
    reason = str(row.get("reason") or "")

    def _money(val: Any) -> str:
        return _fmt_fx(
            val,
            from_currency=native_currency,
            display_currency=display_currency,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=account_currency,
        )

    if shares > 0:
        bits: list[str] = []
        if row.get("sell_trigger") is not None:
            bits.append(f"Sell at {_money(row.get('sell_trigger'))}")
        bits.append(f"all {_fmt_whole_shares(shares)} sh")
        # Explain under/over vs equal-sleeve target (Save & rebalance).
        try:
            target = float(row["equal_target_usd"]) if row.get("equal_target_usd") is not None else None
        except (TypeError, ValueError):
            target = None
        value = row.get("stock_value")
        if value is None:
            value = row.get("mkt_value")
        try:
            value_f = float(value) if value is not None else None
        except (TypeError, ValueError):
            value_f = None
        if target is not None and value_f is not None:
            gap = value_f - target
            if gap < -1.0:
                bits.append(f"under equal target ({_money(value_f)} / {_money(target)})")
                sma_bit = _sma20_clause(row, _money)
                bits.append(
                    f"top-up via Save & rebalance when above SMA20{sma_bit}"
                )
            elif gap > 1.0:
                bits.append(f"over equal target ({_money(value_f)} / {_money(target)})")
        return " · ".join(bits)
    planned = row.get("planned_shares")
    budget = row.get("buy_budget")
    bits = []
    try:
        budget_f = float(budget) if budget is not None else None
    except (TypeError, ValueError):
        budget_f = None
    if isinstance(planned, int) and planned > 0:
        bits.append(f"Buy ~{_fmt_whole_shares(planned)} sh")
        if budget_f is not None:
            bits.append(_money(budget_f))
    elif budget_f is not None and budget_f <= 1e-6:
        # Buy pool is 0 (over-invested / unused=0) — not "broke at IBKR".
        bits.append("no buy-pool room (over budget)")
    elif budget_f is not None:
        bits.append(f"can't afford 1 sh (pool {_money(budget_f)})")
    if "20-hour average" in reason:
        bits.append(f"after 20-hour average clears{_sma20_clause(row, _money)}")
    elif row.get("buy_trigger") is not None:
        bits.append(f"when ≥ {_money(row.get('buy_trigger'))}")
    return " · ".join(bits) if bits else "—"


def _sma20_clause(row: dict[str, Any], money_fmt) -> str:
    """Suffix like ' (SMA20 138.82 USD; now 136.78 USD)' when values exist."""
    try:
        sma_v = float(row["sma20"]) if row.get("sma20") is not None else None
    except (TypeError, ValueError):
        sma_v = None
    try:
        px = float(row["price"]) if row.get("price") is not None else None
    except (TypeError, ValueError):
        px = None
    if sma_v is None:
        return ""
    if px is not None:
        return f" (SMA20 {money_fmt(sma_v)}; now {money_fmt(px)})"
    return f" (SMA20 {money_fmt(sma_v)})"


def _account_holdings_table(
    rows: list[dict[str, Any]],
    *,
    stock_currency: str = "USD",
    display_currency: str = "USD",
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
    account_currency: str | None = None,
) -> list[dict[str, Any]]:
    """One easy table for whole-account mode: position + levels + why.

    Native figures are in the stock trading currency (USD). Display may
    convert to the selected view currency via IBKR FX.
    """
    native = str(stock_currency or "USD").upper()
    display = str(display_currency or native).upper()

    def _cell(val: Any) -> str:
        return _fmt_fx(
            val,
            from_currency=native,
            display_currency=display,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=account_currency,
        )

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
                "Price": _cell(row.get("price")),
                "Value": _cell(
                    row.get("stock_value") if row.get("stock_value") is not None else row.get("mkt_value")
                ),
                "Orders today": orders_txt,
                "Low": _cell(row.get("trough")) if row.get("trough") is not None else "—",
                "High": _cell(row.get("peak")) if row.get("peak") is not None else "—",
                "Next buy/sell": _account_next_plan(
                    row,
                    native_currency=native,
                    display_currency=display,
                    usd_cad_rate=usd_cad_rate,
                    fx_rates=fx_rates,
                    account_currency=account_currency,
                ),
                "Why": str(row.get("reason") or "—"),
            }
        )
    return out


def _holdings_table(
    rows: list[dict[str, Any]],
    *,
    live_book: bool = False,
    use_account_cash: bool = False,
    account_currency: str = "USD",
    stock_currency: str = "USD",
    display_currency: str | None = None,
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Title-case holdings rows. Account mode hides misleading sleeve cash."""
    if live_book and use_account_cash:
        return _account_holdings_table(
            rows,
            stock_currency=stock_currency,
            display_currency=display_currency or stock_currency,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=account_currency,
        )
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


def _render_money_hero(
    st: Any,
    money: dict[str, Any],
    status: dict[str, Any],
    *,
    display_currency: str | None = None,
) -> None:
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

    # Portfolio figures are native account currency (CAD on Canada paper).
    native = str(money.get("account_currency") or status.get("account_currency") or "CAD").upper()
    if native in {"BASE", ""}:
        native = "CAD"
    fx_raw = status.get("usd_cad_rate")
    fx_rate: float | None = float(fx_raw) if isinstance(fx_raw, (int, float)) and float(fx_raw) > 0 else None
    fx_map = status.get("fx_rates") if isinstance(status.get("fx_rates"), dict) else None
    # Stale file marks sometimes label CAD paper as USD when only the FX tag is present.
    if fx_rate is not None and native == "USD":
        native = "CAD"
    display = str(display_currency or native).upper()

    def _port(val: Any) -> str:
        return _fmt_fx(
            val,
            from_currency=native,
            display_currency=display,
            usd_cad_rate=fx_rate,
            fx_rates=fx_map,
            account_currency=native,
        )

    use_account = bool(status.get("use_account_cash", True)) or bool(money.get("use_account_cash"))
    if use_account:
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Account total",
            _port(nav if nav is not None else book),
            help=(
                f"Full broker account value from IBKR (native {native}, shown as {display}). "
                "Includes cash, stock positions, and accrued interest. "
                "Can be higher than Cash even with nothing in stock."
            ),
        )
        c2.metric(
            "In stocks",
            _port(invested),
            help=(
                f"Broker GrossPositionValue (native {native}). "
                "Not the same as summing share marks in the positions table."
            ),
        )
        c3.metric(
            "Cash",
            _port(cash),
            help=(
                f"Broker TotalCashValue (native {native}). "
                "Does not include accrued interest or stock positions."
            ),
        )
        accrued = money.get("accrued_cash")
        if isinstance(accrued, (int, float)) and abs(float(accrued)) >= 0.01:
            st.caption(
                f"Accrued interest {_port(float(accrued))} "
                f"(part of account total; not stock holdings)"
            )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Book capital",
            _port(book),
            help="Starting cash allocated to this bot book.",
        )
        c2.metric(
            "In stocks",
            _port(invested),
            help="Mark-to-market value of shares held in the bot book.",
        )
        c3.metric(
            "In cash",
            _port(cash),
            help="Cash left in the bot book (not yet in shares).",
        )
        c4.metric(
            "Book total",
            _port(nav),
            help="In stocks + In cash for this bot book.",
        )

    if use_account:
        day_help = (
            "Change in full account value vs the prior Eastern calendar day "
            "(from the daily equity log). Includes open positions, cash, "
            "realized trades today, and accrued interest — not share marks alone."
        )
        if day_delta is not None:
            delta_label = _port(day_delta)
            if day_pct is not None:
                st.metric("Day P&L", delta_label, delta=_fmt_pct(day_pct), help=day_help)
            else:
                st.metric("Day P&L", delta_label, help=day_help)
        else:
            st.metric("Day P&L", "—", help=day_help)
    else:
        r1, r2 = st.columns(2)
        r1.metric(
            "Since start",
            _fmt_pct(ret) if ret is not None else "—",
            help="Bot book return versus starting capital.",
        )
        if day_delta is not None:
            delta_label = _port(day_delta)
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
        if display != native and fx_rate is not None:
            bits.append(f"showing {display} (IBKR native {native}, FX {fx_rate:.4f})")
        else:
            bits.append(f"IBKR account in {native}")
        bits.append("bot wallet is Trading budget (below)")
    elif isinstance(broker_cash, (int, float)) and book is not None:
        if abs(float(broker_cash) - float(book)) > 1:
            bits.append(
                f"IBKR paper account cash {_port(broker_cash)} (not bot book)"
            )
    if isinstance(broker_eq, (int, float)) and not use_account:
        bits.append(f"IBKR equity {_port(broker_eq)}")
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


def _reduce_sell_rows(
    plan: list[dict[str, Any]],
    *,
    show_money,
) -> list[dict[str, Any]]:
    """Human table rows for a reduce preview/execute plan."""
    rows: list[dict[str, Any]] = []
    for p in plan:
        if not isinstance(p, dict):
            continue
        shares = p.get("shares")
        try:
            shares_txt = f"{float(shares):g}"
        except (TypeError, ValueError):
            shares_txt = "—"
        price = p.get("price")
        try:
            price_txt = f"{float(price):,.2f} USD"
        except (TypeError, ValueError):
            price_txt = "—"
        rows.append(
            {
                "Symbol": p.get("symbol") or "—",
                "Shares to sell": shares_txt,
                "Price": price_txt,
                "Notional": show_money(p.get("notional")),
            }
        )
    return rows


def _rebalance_order_rows(
    orders: list[dict[str, Any]],
    *,
    show_money,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in orders:
        if not isinstance(p, dict):
            continue
        shares = p.get("shares")
        try:
            shares_txt = f"{float(shares):g}"
        except (TypeError, ValueError):
            shares_txt = "—"
        price = p.get("price")
        try:
            price_txt = f"{float(price):,.2f} USD"
        except (TypeError, ValueError):
            price_txt = "—"
        rows.append(
            {
                "Side": p.get("side") or "—",
                "Symbol": p.get("symbol") or "—",
                "Shares": shares_txt,
                "Price": price_txt,
                "Notional": show_money(p.get("notional")),
                "Target": show_money(p.get("target_usd")),
            }
        )
    return rows


def _rebalance_symbols(
    money: dict[str, Any], status: dict[str, Any], live_paths: LivePaths
) -> list[str]:
    """Active non-exit_only symbols (include flats at 0 shares)."""
    exit_only: set[str] = set()
    picker_paths = PickerPaths(project_root=live_paths.project_root)
    active = load_active(picker_paths.active_selection_path)
    if active is not None:
        for row in active.symbols:
            if row.exit_only:
                exit_only.add(str(row.symbol).upper())
    assets = status.get("assets")
    if isinstance(assets, dict):
        for sym, row in assets.items():
            if isinstance(row, dict) and row.get("exit_only"):
                exit_only.add(str(sym).upper())
    elif isinstance(assets, list):
        for a in assets:
            if isinstance(a, dict) and a.get("exit_only") and a.get("symbol"):
                exit_only.add(str(a["symbol"]).upper())

    ordered: list[str] = []
    seen: set[str] = set()
    for src in (
        status.get("symbols") or [],
        [h.get("symbol") for h in (money.get("holdings") or []) if isinstance(h, dict)],
    ):
        for raw in src:
            if not raw:
                continue
            sym = str(raw).upper()
            if sym in seen or sym in exit_only:
                continue
            seen.add(sym)
            ordered.append(sym)
    return ordered


def _render_trading_budget_section(
    st: Any,
    money: dict[str, Any],
    live_paths: LivePaths,
    *,
    status: dict[str, Any] | None = None,
    display_currency: str = "USD",
    account_currency: str = "CAD",
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
) -> None:
    """Bot wallet: what the strategy may deploy (separate from full IBKR equity)."""
    display = str(display_currency or "USD").upper()
    status = status or {}
    # IBKR ledger rates treat account_currency as 1.0 BASE. Wallet amounts are
    # stored in USD — always convert with the real account book (usually CAD),
    # never account_currency="USD", or USD→CAD becomes a no-op and Save looks broken.
    native = str(account_currency or money.get("account_currency") or "CAD").upper()
    if native in {"BASE", ""}:
        native = "CAD"
    st.subheader("Trading budget")
    st.caption(
        f"Bot wallet (stored in USD for share sizing; amounts shown in **{display}**). "
        "**Save & rebalance** equalizes each *active* (non-exit-only) sleeve to budget÷N "
        "(sell overweight · buy underweight only above SMA20 · US RTH). "
        "It does **not** sell picker **exit-only** drops — those wait for a peak/trough SELL "
        "(or use **Reduce** to free capital). "
        "To change the wallet **without** trading, use **Save wallet only**. "
        "Cash-out (sells only, no equal buys) → **Reduce** below."
    )
    flash = st.session_state.pop("remote_rebalance_flash", None)
    if isinstance(flash, dict):
        level = str(flash.get("level") or "info")
        msg = str(flash.get("message") or "")
        if level == "success":
            st.success(msg)
        elif level == "warning":
            st.warning(msg)
        elif level == "error":
            st.error(msg)
        else:
            st.info(msg)
        orders_flash = flash.get("orders")
        if isinstance(orders_flash, list) and orders_flash:
            _show_table(
                st,
                _rebalance_order_rows(orders_flash, show_money=lambda v: _fmt_fx(
                    v,
                    from_currency="USD",
                    display_currency=display,
                    usd_cad_rate=usd_cad_rate,
                    fx_rates=fx_rates,
                    account_currency=native,
                )),
                "No orders.",
            )
        skipped_flash = flash.get("skipped")
        if isinstance(skipped_flash, list) and skipped_flash:
            st.caption(
                "Skipped: "
                + ", ".join(
                    f"{s.get('symbol')} ({s.get('reason')})"
                    for s in skipped_flash
                    if isinstance(s, dict)
                )
            )
    bud = money.get("trading_budget_usd")
    inv_u = money.get("invested_usd")
    unused = money.get("unused_budget_usd")
    pool = money.get("buy_pool_usd")
    spend_u = money.get("spendable_usd")
    wdraw = money.get("withdrawable_usd")
    symbols_live = _rebalance_symbols(money, status, live_paths)
    n_sleeves = len(symbols_live)
    target_sleeve = (
        float(bud) / float(n_sleeves)
        if isinstance(bud, (int, float)) and n_sleeves > 0
        else None
    )

    def _show(val: Any) -> str:
        return _fmt_fx(
            val,
            from_currency="USD",
            display_currency=display,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=native,
        )

    def _to_display(usd_val: float) -> float:
        converted = _fx_convert(
            usd_val,
            from_currency="USD",
            to_currency=display,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=native,
        )
        return float(converted) if converted is not None else float(usd_val)

    def _from_display(amount: float) -> float:
        if display == "USD":
            return float(amount)
        converted = _fx_convert(
            amount,
            from_currency=display,
            to_currency="USD",
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=native,
        )
        if converted is None:
            raise ValueError(f"Cannot convert {display}→USD (missing FX rate).")
        return float(converted)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Budget", _show(bud), help="Max the bot may keep in stocks (wallet).")
    m2.metric(
        "Per sleeve",
        _show(target_sleeve) if target_sleeve is not None else "—",
        help=f"Equal target = budget ÷ {n_sleeves or 'N'} active sleeves (what Save & rebalance aims for).",
    )
    m3.metric(
        "In stocks",
        _show(inv_u),
        help="Sum of share × USD last price (converted for display).",
    )
    m4.metric(
        "Unused",
        _show(unused),
        help="Budget minus invested. Room left for signal-driven flat buys between rebalances.",
    )
    m5.metric(
        "Buy pool",
        _show(pool),
        help="Signal BUY sizing: min(unused, IBKR spendable). Rebalance ignores this and aims at per-sleeve.",
    )
    st.caption(
        f"IBKR spendable {_show(spend_u)} · withdrawable est. {_show(wdraw)} "
        f"· active sleeves: {', '.join(symbols_live) if symbols_live else '—'}"
    )
    if isinstance(bud, (int, float)) and isinstance(spend_u, (int, float)) and float(bud) > float(spend_u) + 1:
        st.warning("Budget is above IBKR spendable — rebalance/signal buys clamp to cash (never borrow).")
    if (
        isinstance(bud, (int, float))
        and isinstance(inv_u, (int, float))
        and float(inv_u) > float(bud) + 1
    ):
        st.warning(
            "Over-invested vs budget — **Save & rebalance** sells overweight sleeves down; "
            "or use **Reduce** below for pro-rata cash-out (no buys)."
        )

    trading_on = bool(status.get("trading_enabled", True))
    rth_now = is_us_equity_rth(datetime.now(ZoneInfo("UTC")))
    if not trading_on:
        st.warning("Trading is disabled — enable under Safety before Save & rebalance.")
    if not rth_now:
        try:
            nxt = next_rth_open(datetime.now(ZoneInfo("UTC")))
            st.info(
                f"Outside US RTH — **Save & rebalance** is locked. "
                f"Use **Save wallet only**, then rebalance after open "
                f"(~{nxt.astimezone(_ET).strftime('%a %H:%M %Z')})."
            )
        except Exception:  # noqa: BLE001
            st.info(
                "Outside US RTH — **Save & rebalance** is locked. "
                "Use **Save wallet only**, then rebalance during regular hours."
            )

    default_usd = float(bud) if isinstance(bud, (int, float)) else float(pool or spend_u or 0)
    default_display = _to_display(default_usd)
    # Generous display max so CAD/USD conversion never paints the field red and
    # blocks Save (Streamlit ignores out-of-range edits and keeps the old value).
    max_display = max(_to_display(float(TRADING_BUDGET_USD_MAX)), default_display * 2, 1_000_000.0)
    input_key = f"remote_trading_budget_{display}"
    if input_key not in st.session_state:
        st.session_state[input_key] = float(default_display)
    new_bud_display = st.number_input(
        f"Set budget ({display})",
        min_value=0.0,
        max_value=float(max_display),
        step=1000.0,
        format="%.2f",
        key=input_key,
        help=(
            f"Enter amount in {display}. Stored as USD. "
            "Save & rebalance places equal-sleeve orders; Save wallet only does not."
        ),
    )
    rebalance_confirm = st.text_input(
        "Type REBALANCE to unlock Save & rebalance",
        value="",
        key="remote_rebalance_confirm",
        help="Required only for placing equal-sleeve orders. Not needed for Save wallet only.",
    )
    unlocked = rebalance_confirm.strip().upper() == "REBALANCE"
    can_rebalance = unlocked and trading_on and rth_now and bool(symbols_live)

    pcol, rcol, scol = st.columns(3)
    if pcol.button("Preview rebalance", use_container_width=True, key="remote_rebalance_preview"):
        try:
            usd_val = _from_display(float(new_bud_display))
            os.environ.setdefault("IB_CLIENT_ID", str(dashboard_ib_client_id()))
            from app.broker.ibkr import IbkrBroker

            fallback_px = {
                str(h["symbol"]).upper(): float(h["price"])
                for h in (money.get("holdings") or [])
                if isinstance(h, dict)
                and h.get("symbol")
                and isinstance(h.get("price"), (int, float))
            }
            broker = IbkrBroker(dry_run=True)
            try:
                plan = preview_rebalance_from_broker(
                    broker,
                    symbols=symbols_live,
                    budget_usd=usd_val,
                    spendable_usd=float(spend_u or 0),
                    fallback_prices=fallback_px,
                )
            finally:
                ib = getattr(broker, "ib", None)
                if ib is not None and getattr(ib, "isConnected", lambda: False)():
                    ib.disconnect()
            st.caption(
                f"Dry-run target/sleeve {_show(plan.get('target_per_sleeve'))} "
                "(SMA20 from IBKR hourly bars)."
            )
            orders = list(plan.get("orders") or [])
            if orders:
                _show_table(
                    st,
                    _rebalance_order_rows(orders, show_money=_show),
                    "No orders.",
                )
            else:
                st.info("No orders in preview (already equal, gated, or missing prices).")
            skipped = list(plan.get("skipped") or [])
            if skipped:
                st.caption(
                    "Skipped: "
                    + ", ".join(
                        f"{s.get('symbol')} ({s.get('reason')})"
                        for s in skipped
                        if isinstance(s, dict)
                    )
                )
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Preview failed: {exc}")

    if rcol.button(
        "Save & rebalance",
        use_container_width=True,
        key="remote_save_budget",
        disabled=not can_rebalance,
    ):
        try:
            usd_val = _from_display(float(new_bud_display))
            written = set_trading_budget_usd(live_paths, usd_val)
            st.session_state.pop(input_key, None)
            os.environ.setdefault("IB_CLIENT_ID", str(dashboard_ib_client_id()))
            from app.broker.ibkr import IbkrBroker

            broker = IbkrBroker(dry_run=False)
            try:
                result = execute_rebalance_to_equal(
                    broker,
                    symbols=symbols_live,
                    budget_usd=written,
                    dry_run=False,
                    paths=live_paths,
                )
                st.session_state["remote_rebalance_flash"] = {
                    "level": "success",
                    "message": (
                        f"Budget {_show(written)} · target/sleeve "
                        f"{_show(result.get('target_per_sleeve'))} · "
                        f"{len(result.get('sells') or [])} sell(s), "
                        f"{len(result.get('buys') or [])} buy(s)."
                    ),
                    "orders": list(result.get("orders") or []),
                    "skipped": list(result.get("skipped") or []),
                }
            finally:
                ib = getattr(broker, "ib", None)
                if ib is not None and getattr(ib, "isConnected", lambda: False)():
                    ib.disconnect()
            st.rerun()
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save & rebalance failed: {exc}")

    if scol.button(
        "Save wallet only",
        use_container_width=True,
        key="remote_save_wallet_only",
        help="Persist trading_budget_usd with no orders.",
    ):
        try:
            usd_val = _from_display(float(new_bud_display))
            written = set_trading_budget_usd(live_paths, usd_val)
            st.session_state.pop(input_key, None)
            st.session_state["remote_rebalance_flash"] = {
                "level": "success",
                "message": (
                    f"Wallet saved: {_show(written)} (stored {written:,.2f} USD). "
                    "No orders placed."
                ),
            }
            st.rerun()
        except (ValueError, FileNotFoundError) as exc:
            st.error(str(exc))

    with st.expander("Cash out / Reduce to budget", expanded=False):
        st.caption(
            "Pro-rata **sells only** down to the **saved** budget (no buys; "
            "budget **0** = flatten listed longs). Prefer **Disable trading** under Safety first. "
            "Withdraw freed cash in IBKR yourself. For equal sleeves use **Save & rebalance** above."
        )
        confirm = st.text_input(
            "Type REDUCE to unlock execute",
            value="",
            key="remote_reduce_confirm",
        )
        r1, r2 = st.columns(2)
        if r1.button("Preview sells", use_container_width=True, key="remote_reduce_preview"):
            try:
                saved = (
                    float(bud)
                    if isinstance(bud, (int, float))
                    else _from_display(float(new_bud_display))
                )
            except ValueError as exc:
                st.error(str(exc))
                saved = None
            if saved is not None:
                pos_map = {
                    str(h.get("symbol")): float(h.get("shares") or 0)
                    for h in (money.get("holdings") or [])
                    if h.get("symbol")
                }
                px_map = {
                    str(h.get("symbol")): float(h["price"])
                    for h in (money.get("holdings") or [])
                    if h.get("symbol") and isinstance(h.get("price"), (int, float))
                }
                plan = preview_reduce_to_budget(
                    positions=pos_map, prices=px_map, budget_usd=saved
                )
                if not plan:
                    st.info("Nothing to sell — already at or under budget.")
                else:
                    _show_table(
                        st,
                        _reduce_sell_rows(plan, show_money=_show),
                        "Nothing to sell.",
                    )
                    notion = sum(float(p.get("notional") or 0) for p in plan)
                    st.caption(f"Total notional ≈ {_show(notion)}")
        if r2.button(
            "Execute reduce",
            use_container_width=True,
            key="remote_reduce_exec",
            disabled=confirm.strip().upper() != "REDUCE",
        ):
            try:
                saved = (
                    float(bud)
                    if isinstance(bud, (int, float))
                    else _from_display(float(new_bud_display))
                )
            except ValueError as exc:
                st.error(str(exc))
                saved = None
            if saved is not None:
                try:
                    set_trading_budget_usd(live_paths, saved)
                    os.environ.setdefault("IB_CLIENT_ID", str(dashboard_ib_client_id()))
                    from app.broker.ibkr import IbkrBroker

                    broker = IbkrBroker(dry_run=False)
                    try:
                        result = execute_reduce_to_budget(
                            broker,
                            budget_usd=saved,
                            dry_run=False,
                            paths=live_paths,
                        )
                        sells = result.get("sells") or []
                        st.success(
                            f"Reduce done: {len(sells)} sell(s), "
                            f"≈ {_show(result.get('notional', 0))}"
                        )
                        if sells:
                            _show_table(
                                st,
                                _reduce_sell_rows(sells, show_money=_show),
                                "No sells.",
                            )
                    finally:
                        ib = getattr(broker, "ib", None)
                        if ib is not None and getattr(ib, "isConnected", lambda: False)():
                            ib.disconnect()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Reduce failed: {exc}")


def _render_live_safety_controls(st: Any, live_paths: LivePaths, status: dict[str, Any]) -> None:
    """Pause/resume, risk ack, and order-cap — not capital sizing."""
    st.subheader("Safety & limits")
    st.caption("Pause trading, acknowledge risk incidents, and per-symbol daily order caps.")
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
    by_sym = (
        status.get("orders_today_by_symbol")
        if isinstance(status.get("orders_today_by_symbol"), dict)
        else {}
    )
    busiest = 0
    for v in by_sym.values():
        try:
            busiest = max(busiest, int(v or 0))
        except (TypeError, ValueError):
            continue
    left = max(0, current_cap - busiest)
    with st.expander("Daily order limit (per symbol)", expanded=False):
        st.caption(
            f"Each ticker may submit up to **{current_cap}** broker orders per Eastern day. "
            f"Busiest today: **{busiest}** used · **{left}** left. "
            "Does not clear a risk stop — use Ack risk if blocked."
        )
        cap_col, btn_col = st.columns([2, 1])
        new_cap = cap_col.number_input(
            "Per-symbol limit",
            min_value=DAILY_ORDER_CAP_MIN,
            max_value=DAILY_ORDER_CAP_MAX,
            value=min(max(current_cap, DAILY_ORDER_CAP_MIN), DAILY_ORDER_CAP_MAX),
            step=1,
            key="remote_daily_order_cap",
        )
        if btn_col.button("Save limit", use_container_width=True, key="remote_save_order_cap"):
            try:
                written = set_daily_order_cap(live_paths, int(new_cap))
                st.success(f"Per-symbol daily order cap set to {written}.")
                st.rerun()
            except (ValueError, FileNotFoundError) as exc:
                st.error(str(exc))


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


def _render_performance_chart(
    st: Any,
    nav_path: Path,
    *,
    native_currency: str = "CAD",
    display_currency: str | None = None,
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
) -> None:
    """Day-to-day account equity under the positions table."""
    st.subheader("Performance")
    points = load_daily_nav(nav_path)
    if not points:
        st.caption("Day-to-day equity chart appears after the worker logs account value.")
        return
    native = str(native_currency or "CAD").upper()
    display = str(display_currency or native).upper()

    def _eq(val: Any) -> str:
        return _fmt_fx(
            val,
            from_currency=native,
            display_currency=display,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=native,
        )

    def _as_display(val: Any) -> float | None:
        return _fx_convert(
            val,
            from_currency=native,
            to_currency=display,
            usd_cad_rate=usd_cad_rate,
            fx_rates=fx_rates,
            account_currency=native,
        )

    first = points[0]
    last = points[-1]
    since = None
    if first["equity"] and first["equity"] > 0:
        since = ((float(last["equity"]) - float(first["equity"])) / float(first["equity"])) * 100.0
    bits = [
        f"{len(points)} day(s)",
        f"{first['date']} → {last['date']}",
        f"latest {_eq(last['equity'])}",
    ]
    if since is not None and len(points) >= 2:
        bits.append(f"since first log {_fmt_pct(since)}")
    st.caption(" · ".join(bits) + " · one point per Eastern calendar day (IBKR account equity)")

    if len(points) == 1:
        st.info(f"Logged {_eq(points[0]['equity'])} on {points[0]['date']}. Chart needs 2+ days.")
        return

    try:
        import pandas as pd
    except ImportError:
        st.caption("pandas required for chart")
        return

    chart_points = []
    for p in points:
        eq = _as_display(p["equity"])
        chart_points.append({"date": p["date"], "equity": eq if eq is not None else p["equity"]})
    frame = pd.DataFrame(chart_points)
    chart = frame.set_index("date")[["equity"]].rename(
        columns={"equity": f"Account equity ({display})"}
    )
    st.line_chart(chart, height=280)

    recent = list(reversed(points[-14:]))
    rows = []
    for row in recent:
        ch = row.get("day_change")
        pct = row.get("day_change_pct")
        rows.append(
            {
                "Date": row["date"],
                "Equity": _eq(row["equity"]),
                "Day change": _eq(ch) if ch is not None else "—",
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
        "IBKR paper / live · account → budget → positions → safety",
        refresh_key="remote_live_refresh",
    )
    status = load_live_status(live_paths.state_dir)
    # Always overlay IBKR marks so portfolio currency comes from the broker
    # (CAD on Canada paper), not a stale file default of USD.
    status = _try_ibkr_marks(status)
    if not refresh and status.get("marks_source") == "files":
        pass  # gateway down — fall back to last saved state
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

    use_account = bool(status.get("use_account_cash", True))
    last_preview = status.get("last_cycle") or {}
    cycle_reasons: dict[str, str] = {}
    sma20_by_symbol: dict[str, float] = {}
    if isinstance(last_preview, dict):
        for d in last_preview.get("decisions") or []:
            if not isinstance(d, dict) or not d.get("symbol"):
                continue
            sym = str(d["symbol"]).upper()
            if d.get("signal_reason"):
                cycle_reasons[sym] = str(d["signal_reason"])
            if isinstance(d.get("sma20"), (int, float)) and float(d["sma20"]) > 0:
                sma20_by_symbol[sym] = float(d["sma20"])
    # Prefer live IB overlay SMA when marks refresh succeeded.
    overlay_sma = status.get("sma20_by_symbol")
    if isinstance(overlay_sma, dict):
        for k, v in overlay_sma.items():
            try:
                sma20_by_symbol[str(k).upper()] = float(v)
            except (TypeError, ValueError):
                continue
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
        account_currency=str(status.get("account_currency") or "")
        if status.get("account_currency")
        else None,
        usd_cad_rate=float(status["usd_cad_rate"])
        if isinstance(status.get("usd_cad_rate"), (int, float))
        else None,
        fx_rates=status.get("fx_rates") if isinstance(status.get("fx_rates"), dict) else None,
        trading_budget_usd=float(status["trading_budget_usd"])
        if isinstance(status.get("trading_budget_usd"), (int, float))
        else None,
        cycle_reasons=cycle_reasons,
        orders_today_by_symbol=status.get("orders_today_by_symbol")
        if isinstance(status.get("orders_today_by_symbol"), dict)
        else None,
        sma20_by_symbol=sma20_by_symbol or None,
    )
    acct_ccy = str(money.get("account_currency") or status.get("account_currency") or "CAD").upper()
    if acct_ccy in {"BASE", ""}:
        acct_ccy = "CAD"
    fx = status.get("usd_cad_rate")
    fx_rate = float(fx) if isinstance(fx, (int, float)) and float(fx) > 0 else None
    fx_map = status.get("fx_rates") if isinstance(status.get("fx_rates"), dict) else None

    # --- Account (IBKR bank) ---
    head_l, head_r = st.columns([2, 1])
    with head_l:
        st.subheader("Account")
        st.caption("Full IBKR balances (can be larger than what the bot trades).")
    with head_r:
        display_ccy = _display_currency_toggle(
            st,
            account_currency=acct_ccy,
            usd_cad_rate=fx_rate,
            fx_rates=fx_map,
        )

    _render_money_hero(st, money, status, display_currency=display_ccy)
    _render_edge_strip(st, money.get("edge") or {}, money.get("bot_return_pct"))

    last = status.get("last_cycle") or {}
    decisions = last.get("decisions") if isinstance(last, dict) else None
    when = None
    if isinstance(last, dict):
        when = last.get("at_eastern") or (
            _fmt_eastern(str(last["at_utc"])) if last.get("at_utc") else None
        )

    # --- Bot wallet ---
    if use_account:
        st.divider()
        _render_trading_budget_section(
            st,
            money,
            live_paths,
            status=status,
            display_currency=display_ccy,
            account_currency=acct_ccy,
            usd_cad_rate=fx_rate,
            fx_rates=fx_map,
        )

    # --- Positions ---
    st.divider()
    if use_account:
        st.subheader("Positions")
        cap = int(status.get("daily_order_cap") or 5)
        stock_ccy = "USD"
        if fx_rate is not None and display_ccy != stock_ccy:
            fx_note = (
                f"Marks shown in {display_ccy} "
                f"(stocks trade in {stock_ccy}; FX {fx_rate:.4f}). "
            )
        elif fx_rate is not None:
            fx_note = f"Amounts in {display_ccy}. "
        else:
            fx_note = f"Amounts in {stock_ccy}. "
        st.caption(
            fx_note
            + f"Orders today capped at **{cap}/symbol** (Safety & limits). "
            "Signal buys use **buy pool**; equal sleeves use **Save & rebalance**."
        )
        _show_table(
            st,
            _holdings_table(
                money.get("holdings") or [],
                live_book=True,
                use_account_cash=True,
                account_currency=acct_ccy,
                stock_currency=stock_ccy,
                display_currency=display_ccy,
                usd_cad_rate=fx_rate,
                fx_rates=fx_map,
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
        _render_performance_chart(
            st,
            live_paths.account_nav_path,
            native_currency=acct_ccy,
            display_currency=display_ccy,
            usd_cad_rate=fx_rate,
            fx_rates=fx_map,
        )
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

    # --- Safety (bottom) ---
    st.divider()
    _render_live_safety_controls(st, live_paths, status)


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

    st.subheader("Schedule")
    next_rank_label = _fmt_eastern(status.get("next_rank_at_utc"))
    st.info(
        f"**Next ranking analysis:** {next_rank_label}  \n"
        "Weekly Saturday midnight Eastern fire; CLI keeps **every other** Saturday "
        "(skip window ~10 days). Skips email + show under **Last timer outcome**."
    )

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

    last_status = status.get("last_rank_status") if isinstance(status.get("last_rank_status"), dict) else None
    if last_status:
        st.subheader("Last timer outcome")
        st.caption(
            f"`{last_status.get('status')}` · "
            f"{_fmt_eastern(last_status.get('at_utc'))} · "
            f"{last_status.get('reason') or last_status.get('run_id') or '—'}"
        )
        if last_status.get("status") == "skipped":
            st.warning(
                "Biweekly skip window — no new pending. "
                "Force with `PICKER_FORCE=1` / `--force` if you need a ranking now."
            )

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
