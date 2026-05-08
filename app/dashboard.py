from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
CONFIG_PATH = STATE_DIR / "config.json"
STATE_PATH = STATE_DIR / "state.json"
TRADES_PATH = STATE_DIR / "trades.csv"
EQUITY_PATH = STATE_DIR / "equity.csv"
PARAMS_PATH = STATE_DIR / "params_history.csv"
PORTFOLIO_PATH = STATE_DIR / "portfolio.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def commit_file_to_github(path: Path, message: str) -> tuple[bool, str]:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_BRANCH", "main")
    if not token or not repo:
        return False, "GITHUB_TOKEN/GITHUB_REPOSITORY not set; saved locally only."
    rel_path = str(path.relative_to(ROOT)).replace("\\", "/")
    url = f"https://api.github.com/repos/{repo}/contents/{rel_path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    sha = None
    req_get = urllib.request.Request(url + f"?ref={branch}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req_get, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            sha = payload.get("sha")
    except urllib.error.HTTPError:
        sha = None

    content = base64.b64encode(path.read_bytes()).decode("utf-8")
    body = {"message": message, "content": content, "branch": branch}
    if sha:
        body["sha"] = sha
    req_put = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req_put, timeout=20):
            return True, "Saved and committed to GitHub."
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed to commit to GitHub: {exc}"


def trigger_workflow() -> tuple[bool, str]:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        return False, "Set GITHUB_TOKEN and GITHUB_REPOSITORY to use manual run."
    url = f"https://api.github.com/repos/{repo}/actions/workflows/hourly.yml/dispatches"
    body = {"ref": os.getenv("GITHUB_BRANCH", "main")}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True, "Workflow dispatched."
    except Exception as exc:  # noqa: BLE001
        return False, f"Workflow trigger failed: {exc}"


def read_json_or_default(path: Path, default_value: dict) -> dict:
    if not path.exists():
        return default_value
    return read_json(path)


def build_default_portfolio(config: dict, state: dict) -> dict:
    return {
        "cash": float(state.get("cash", 0.0)),
        "positions": [
            {
                "symbol": str(config.get("symbol", "")).upper(),
                "shares": float(state.get("shares", 0.0)),
                "price": float(state.get("last_price", 0.0)),
                "cost_basis": 0.0,
                "notes": "Strategy position",
            }
        ],
        "watchlist": [],
    }


def normalize_assets_from_config(config: dict) -> list[dict]:
    assets = config.get("assets")
    if isinstance(assets, list) and assets:
        out = []
        for row in assets:
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            out.append(
                {
                    "symbol": symbol,
                    "buy_rise_pct": float(row.get("buy_rise_pct", config.get("buy_rise_pct", 1.0))),
                    "sell_drop_pct": float(row.get("sell_drop_pct", config.get("sell_drop_pct", 1.5))),
                    "x_days": int(row.get("x_days", config.get("x_days", 20))),
                    "reopt_days": int(row.get("reopt_days", config.get("reopt_days", 5))),
                    "enabled": bool(row.get("enabled", True)),
                }
            )
        if out:
            return out
    return [
        {
            "symbol": str(config.get("symbol", "")).strip().upper(),
            "buy_rise_pct": float(config.get("buy_rise_pct", 1.0)),
            "sell_drop_pct": float(config.get("sell_drop_pct", 1.5)),
            "x_days": int(config.get("x_days", 20)),
            "reopt_days": int(config.get("reopt_days", 5)),
            "enabled": True,
        }
    ]


def format_timestamp_in_timezone(raw_timestamp: str | None, tz_name: str) -> str:
    if not raw_timestamp:
        return "Never"
    try:
        ts_utc = pd.to_datetime(raw_timestamp, utc=True)
        local_ts = ts_utc.tz_convert(ZoneInfo(tz_name))
        return local_ts.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:  # noqa: BLE001
        return str(raw_timestamp)


def notify(ok: bool, msg: str) -> None:
    st.session_state["dashboard_notice"] = {"ok": bool(ok), "msg": str(msg)}


def normalize_symbol(raw_value: object, default_suffix: str = "") -> str:
    symbol = str(raw_value or "").strip().upper()
    if symbol in {"", "NONE", "NAN"}:
        return ""
    if "." not in symbol and default_suffix:
        return f"{symbol}{default_suffix}"
    return symbol


def render_notice() -> None:
    notice = st.session_state.get("dashboard_notice")
    if not notice:
        return
    left, right = st.columns([0.88, 0.12])
    with left:
        if bool(notice.get("ok", False)):
            st.success(str(notice.get("msg", "")))
        else:
            st.warning(str(notice.get("msg", "")))
    with right:
        if st.button("Dismiss", key="dismiss_dashboard_notice"):
            st.session_state.pop("dashboard_notice", None)
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Trade Signal Dashboard", layout="wide")
    st.title("Autonomous Trade Alert Dashboard")
    render_notice()
    display_tz = st.sidebar.text_input(
        "Display timezone",
        value=os.getenv("DASHBOARD_TIMEZONE", "America/Toronto"),
        help="Use an IANA timezone like America/Toronto, America/New_York, or Asia/Ho_Chi_Minh.",
    ).strip()

    config = read_json(CONFIG_PATH)
    state = read_json(STATE_PATH)
    trades = read_csv_or_empty(TRADES_PATH)
    equity = read_csv_or_empty(EQUITY_PATH)
    params_hist = read_csv_or_empty(PARAMS_PATH)
    portfolio = read_json_or_default(PORTFOLIO_PATH, build_default_portfolio(config=config, state=state))
    strategy_assets = normalize_assets_from_config(config)

    positions_df = pd.DataFrame(portfolio.get("positions", []))
    if positions_df.empty:
        positions_df = pd.DataFrame(columns=["symbol", "shares", "price", "cost_basis", "notes"])
    for col, default in [("symbol", ""), ("shares", 0.0), ("price", 0.0), ("cost_basis", 0.0), ("notes", "")]:
        if col not in positions_df.columns:
            positions_df[col] = default
    positions_df["symbol"] = positions_df["symbol"].astype(str).str.upper().str.strip()
    positions_df["shares"] = pd.to_numeric(positions_df["shares"], errors="coerce").fillna(0.0)
    positions_df["price"] = pd.to_numeric(positions_df["price"], errors="coerce").fillna(0.0)
    positions_df["cost_basis"] = pd.to_numeric(positions_df["cost_basis"], errors="coerce").fillna(0.0)
    positions_df["market_value"] = positions_df["shares"] * positions_df["price"]
    portfolio_cash = float(portfolio.get("cash", 0.0))
    total_market_value = float(positions_df["market_value"].sum())
    total_portfolio_value = portfolio_cash + total_market_value
    strategy_value = float(state.get("cash", 0.0) + state.get("shares", 0.0) * state.get("last_price", 0.0))

    st.markdown(
        """
        **How this app is organized**
        - **Bot (Automation)**: configure and run automated signal checks.
        - **Portfolio (Manual)**: track your real holdings/cash across many symbols.
        - **History**: review trade and re-optimization logs.
        """
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Automation Assets", str(len([a for a in strategy_assets if a.get("enabled", True)])))
    c2.metric("Last Action", state.get("last_action", "N/A"))
    c3.metric("Tracked Portfolio", f"{total_portfolio_value:,.2f}")
    c4.metric("Strategy Value", f"{strategy_value:,.2f}")
    c5.metric("Open Positions", str(int((positions_df["shares"] > 0).sum())))
    st.caption(f"Raw UTC timestamp: {state.get('last_run_at', 'Never')}")
    st.caption(f"Last Run (local): {format_timestamp_in_timezone(state.get('last_run_at'), display_tz)}")
    st.info("Automation and portfolio tracking are separate: bot settings control alerts, while portfolio values are manually editable for your real account view.")

    bot_tab, portfolio_tab, history_tab, overview_tab, howto_tab = st.tabs(
        ["Bot (Automation)", "Portfolio (Manual)", "History", "Overview", "How To"]
    )

    with bot_tab:
        st.subheader("Bot Controls")
        st.caption("Use this page to configure automated signal checks and trigger runs.")
        st.caption("Ticker format uses Yahoo symbols (example: `ZSP.TO`, `AAPL`, `MSFT`).")
        assets_df = pd.DataFrame(strategy_assets)
        edited_assets = st.data_editor(
            assets_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "symbol": st.column_config.TextColumn("Symbol", required=True),
                "buy_rise_pct": st.column_config.NumberColumn("Buy rise %", min_value=0.1, max_value=30.0, step=0.1),
                "sell_drop_pct": st.column_config.NumberColumn("Sell drop %", min_value=0.1, max_value=30.0, step=0.1),
                "x_days": st.column_config.NumberColumn("x days", min_value=5, max_value=365, step=1),
                "reopt_days": st.column_config.NumberColumn("reopt every N days", min_value=1, max_value=30, step=1),
                "enabled": st.column_config.CheckboxColumn("Enabled"),
            },
        )
        with st.form("config_form"):
            initial_cash = st.number_input(
                "Initial cash per asset",
                min_value=100.0,
                value=float(config.get("initial_cash", 1000.0)),
                step=100.0,
                help="Each enabled asset starts with this same amount.",
            )
            alerts_enabled = st.checkbox("Email alerts enabled", value=bool(config.get("alerts_enabled", True)))
            save = st.form_submit_button("Save bot settings")
            if save:
                clean_assets = edited_assets.copy()
                default_suffix = ""
                base_symbol = str(config.get("symbol", "")).strip().upper()
                if "." in base_symbol:
                    default_suffix = "." + base_symbol.split(".", 1)[1]
                clean_assets["symbol"] = clean_assets["symbol"].apply(lambda v: normalize_symbol(v, default_suffix=default_suffix))
                clean_assets = clean_assets[clean_assets["symbol"] != ""]
                clean_assets["buy_rise_pct"] = pd.to_numeric(clean_assets["buy_rise_pct"], errors="coerce").fillna(1.0)
                clean_assets["sell_drop_pct"] = pd.to_numeric(clean_assets["sell_drop_pct"], errors="coerce").fillna(1.5)
                clean_assets["x_days"] = pd.to_numeric(clean_assets["x_days"], errors="coerce").fillna(20).astype(int)
                clean_assets["reopt_days"] = pd.to_numeric(clean_assets["reopt_days"], errors="coerce").fillna(5).astype(int)
                if "enabled" not in clean_assets.columns:
                    clean_assets["enabled"] = True
                clean_assets["enabled"] = clean_assets["enabled"].fillna(True).astype(bool)
                if clean_assets.empty:
                    notify(False, "Add at least one asset before saving.")
                else:
                    primary = clean_assets.iloc[0]
                    config.update(
                        {
                            "symbol": str(primary["symbol"]),
                            "buy_rise_pct": float(primary["buy_rise_pct"]),
                            "sell_drop_pct": float(primary["sell_drop_pct"]),
                            "x_days": int(primary["x_days"]),
                            "reopt_days": int(primary["reopt_days"]),
                            "initial_cash": float(initial_cash),
                            "alerts_enabled": bool(alerts_enabled),
                            "assets": clean_assets.to_dict(orient="records"),
                        }
                    )
                    write_json(CONFIG_PATH, config)
                    ok, msg = commit_file_to_github(CONFIG_PATH, "Update trading config from dashboard")
                    notify(ok, msg)

        if st.button("Run check now"):
            ok, msg = trigger_workflow()
            notify(ok, msg)

        st.subheader("Manual Strategy State Override")
        st.caption("Only use this if strategy state is out of sync and needs correction.")
        with st.form("strategy_state_form"):
            state_cash = st.number_input("Strategy Cash", min_value=0.0, value=float(state.get("cash", 0.0)), step=100.0)
            state_shares = st.number_input("Strategy Shares", min_value=0.0, value=float(state.get("shares", 0.0)), step=0.1)
            state_price = st.number_input("Last Price", min_value=0.0, value=float(state.get("last_price", 0.0)), step=0.01)
            override = st.form_submit_button("Apply strategy override")
            if override:
                state["cash"] = float(state_cash)
                state["shares"] = float(state_shares)
                state["last_price"] = float(state_price)
                write_json(STATE_PATH, state)
                ok, msg = commit_file_to_github(STATE_PATH, "Update strategy state from dashboard")
                notify(ok, msg)

    with portfolio_tab:
        st.subheader("Portfolio Manager")
        st.caption("Use this page as your manual account tracker (cash + holdings).")
        portfolio_cash_input = st.number_input("Cash Balance", min_value=0.0, value=portfolio_cash, step=100.0)
        editor_df = positions_df[["symbol", "shares", "price", "cost_basis", "notes"]].copy()
        edited_positions = st.data_editor(
            editor_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "symbol": st.column_config.TextColumn("Symbol", required=True),
                "shares": st.column_config.NumberColumn("Shares", min_value=0.0, step=0.01),
                "price": st.column_config.NumberColumn("Price", min_value=0.0, step=0.01),
                "cost_basis": st.column_config.NumberColumn("Avg Cost", min_value=0.0, step=0.01),
                "notes": st.column_config.TextColumn("Notes"),
            },
        )
        watchlist_text = st.text_input(
            "Watchlist symbols (comma-separated)",
            value=", ".join(portfolio.get("watchlist", [])),
            help="Example: SPY, QQQ, AAPL, MSFT",
        )
        if st.button("Save portfolio"):
            clean_df = edited_positions.copy()
            clean_df["symbol"] = clean_df["symbol"].apply(normalize_symbol)
            clean_df = clean_df[clean_df["symbol"] != ""]
            clean_df["shares"] = pd.to_numeric(clean_df["shares"], errors="coerce").fillna(0.0)
            clean_df["price"] = pd.to_numeric(clean_df["price"], errors="coerce").fillna(0.0)
            clean_df["cost_basis"] = pd.to_numeric(clean_df["cost_basis"], errors="coerce").fillna(0.0)
            clean_df["notes"] = clean_df["notes"].fillna("").astype(str)
            watchlist = [s.strip().upper() for s in watchlist_text.split(",") if s.strip()]
            portfolio = {
                "cash": float(portfolio_cash_input),
                "positions": clean_df[["symbol", "shares", "price", "cost_basis", "notes"]].to_dict(orient="records"),
                "watchlist": watchlist,
            }
            write_json(PORTFOLIO_PATH, portfolio)
            ok, msg = commit_file_to_github(PORTFOLIO_PATH, "Update portfolio from dashboard")
            notify(ok, msg)
            st.rerun()

    with history_tab:
        left, right = st.columns(2)
        with left:
            st.subheader("Recent Trades")
            st.dataframe(trades.tail(100), use_container_width=True, hide_index=True)
        with right:
            st.subheader("Recent Re-optimizations")
            st.dataframe(params_hist.tail(100), use_container_width=True, hide_index=True)
        st.subheader("Last Signal Reason")
        st.code(str(state.get("last_signal_reason", "No reason available")))

    with overview_tab:
        st.subheader("Portfolio Allocation")
        alloc_df = positions_df[positions_df["market_value"] > 0].copy()
        if not alloc_df.empty and total_market_value > 0:
            alloc_df["weight_pct"] = (alloc_df["market_value"] / total_market_value) * 100.0
            pie = go.Figure(
                data=[
                    go.Pie(
                        labels=alloc_df["symbol"],
                        values=alloc_df["market_value"],
                        hole=0.45,
                        textinfo="label+percent",
                    )
                ]
            )
            pie.update_layout(margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(pie, use_container_width=True)
        else:
            st.info("No active positions yet. Add holdings in Portfolio Manager.")

        st.subheader("Strategy Equity Curve")
        if not equity.empty:
            equity["Datetime"] = pd.to_datetime(equity["Datetime"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=equity["Datetime"], y=equity["Portfolio_Value"], mode="lines", name="Portfolio Value"))
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No equity data yet.")

        st.subheader("Current Holdings")
        holdings_view = positions_df[["symbol", "shares", "price", "market_value", "cost_basis", "notes"]].copy()
        st.dataframe(holdings_view.sort_values("market_value", ascending=False), use_container_width=True, hide_index=True)

    with howto_tab:
        st.subheader("How to use this dashboard")
        st.markdown(
            """
            **Daily workflow**
            1. Open **Bot (Automation)** and keep your automated asset list/settings up to date.
            2. Click **Run check now** when you want to trigger a manual workflow run.
            3. Use **Portfolio (Manual)** to maintain cash and holdings for your real account view.
            4. Use **History** to inspect recent trades and threshold re-optimizations.
            5. Use **Overview** for high-level visuals and allocation.

            **Important behavior**
            - The bot and manual portfolio tracker are separate so you can compare model vs real holdings.
            - Automated worker supports multiple enabled assets from the bot table.
            - Every enabled bot asset uses the same initial cash amount (per-asset setting).
            """
        )


if __name__ == "__main__":
    main()
