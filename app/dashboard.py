from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
try:
    from app.data import download_hourly, hourly_limit_start_date
    from app.strategy import optimize_params
except ModuleNotFoundError:
    from data import download_hourly, hourly_limit_start_date
    from strategy import optimize_params


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
CONFIG_PATH = STATE_DIR / "config.json"
STATE_PATH = STATE_DIR / "state.json"
TRADES_PATH = STATE_DIR / "trades.csv"
EQUITY_PATH = STATE_DIR / "equity.csv"
PARAMS_PATH = STATE_DIR / "params_history.csv"


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
                    "reinit_params": bool(row.get("reinit_params", False)),
                }
            )
        if out:
            return out
    return []


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


def initialize_asset_params(assets_df: pd.DataFrame, initial_cash: float) -> tuple[pd.DataFrame, list[str]]:
    """Fill missing per-asset params using trailing 1Y hourly data."""
    if assets_df.empty:
        return assets_df, []

    out = assets_df.copy()
    notes: list[str] = []
    now_utc = datetime.now(timezone.utc)
    start_date = max(
        datetime.strptime(hourly_limit_start_date(), "%Y-%m-%d").date(),
        (now_utc - timedelta(days=365)).date(),
    )
    end_date = (now_utc.date() + timedelta(days=1)).isoformat()

    for idx, row in out.iterrows():
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue

        force_reinit = bool(row.get("reinit_params", False))
        buy_missing = pd.isna(row.get("buy_rise_pct")) or float(row.get("buy_rise_pct", 0.0) or 0.0) <= 0
        sell_missing = pd.isna(row.get("sell_drop_pct")) or float(row.get("sell_drop_pct", 0.0) or 0.0) <= 0
        x_missing = pd.isna(row.get("x_days")) or int(row.get("x_days", 0) or 0) <= 0
        reopt_missing = pd.isna(row.get("reopt_days")) or int(row.get("reopt_days", 0) or 0) <= 0
        if not (force_reinit or buy_missing or sell_missing or x_missing or reopt_missing):
            continue

        try:
            hist = download_hourly(symbol=symbol, start=str(start_date), end=end_date)
            prices = hist["Close"].astype(float).to_numpy()
            if len(prices) < 2:
                raise RuntimeError("insufficient hourly candles")
            best_buy, best_sell, _ = optimize_params(train_prices=prices, initial_cash=float(initial_cash))
            if force_reinit or buy_missing:
                out.at[idx, "buy_rise_pct"] = round(best_buy * 100.0, 3)
            if force_reinit or sell_missing:
                out.at[idx, "sell_drop_pct"] = round(best_sell * 100.0, 3)
            if force_reinit or x_missing:
                out.at[idx, "x_days"] = 20
            if force_reinit or reopt_missing:
                out.at[idx, "reopt_days"] = 5
            notes.append(f"{symbol}: initialized params from 1Y hourly data")
        except Exception as exc:  # noqa: BLE001
            if buy_missing:
                out.at[idx, "buy_rise_pct"] = 1.0
            if sell_missing:
                out.at[idx, "sell_drop_pct"] = 1.5
            if x_missing:
                out.at[idx, "x_days"] = 20
            if reopt_missing:
                out.at[idx, "reopt_days"] = 5
            notes.append(f"{symbol}: using defaults (data init failed: {exc})")
        out.at[idx, "reinit_params"] = False

    return out, notes


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            .main-title {
                font-size: 2rem;
                font-weight: 700;
                margin-bottom: 0.15rem;
            }
            .subtitle {
                color: #6b7280;
                margin-bottom: 1rem;
            }
            .section-note {
                background: #f8fafc;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 0.65rem 0.9rem;
                margin-bottom: 0.8rem;
            }
            .small-muted {
                color: #6b7280;
                font-size: 0.9rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_price_snapshot(strategy_assets: list[dict], state: dict, display_tz: str) -> pd.DataFrame:
    asset_states = state.get("assets", {})
    rows: list[dict] = []
    for asset in strategy_assets:
        symbol = str(asset.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        s = asset_states.get(symbol, {})
        rows.append(
            {
                "symbol": symbol,
                "run_in_live_bot": bool(asset.get("enabled", True)),
                "last_price": float(s.get("last_price", 0.0)) if s.get("last_price") is not None else None,
                "pulled_at_local": format_timestamp_in_timezone(s.get("last_bar_at"), display_tz),
                "last_action": s.get("last_action", "N/A"),
                "signal_reason": s.get("last_signal_reason", "N/A"),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["symbol", "run_in_live_bot", "last_price", "pulled_at_local", "last_action", "signal_reason"]
        )
    return pd.DataFrame(rows).sort_values(["run_in_live_bot", "symbol"], ascending=[False, True]).reset_index(drop=True)


def main() -> None:
    st.set_page_config(page_title="Autonomous Trade Alert Dashboard", layout="wide")
    inject_styles()
    st.markdown('<div class="main-title">Autonomous Trade Alert Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Clean control center for multi-asset signal automation.</div>',
        unsafe_allow_html=True,
    )
    render_notice()

    display_tz = st.sidebar.text_input(
        "Display timezone",
        value=os.getenv("DASHBOARD_TIMEZONE", "America/Toronto"),
        help="Use an IANA timezone like America/Toronto, America/New_York, or Asia/Ho_Chi_Minh.",
    ).strip()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Run Status")
    st.sidebar.caption("Worker schedule: every 10 minutes, Monday-Friday.")
    st.sidebar.caption("Need an immediate pull? Use `Run check now` in Bot Setup.")

    config = read_json(CONFIG_PATH)
    state = read_json(STATE_PATH)
    trades = read_csv_or_empty(TRADES_PATH)
    equity = read_csv_or_empty(EQUITY_PATH)
    params_hist = read_csv_or_empty(PARAMS_PATH)
    strategy_assets = normalize_assets_from_config(config)

    st.markdown(
        """
        <div class="section-note">
        <b>Workspace layout</b><br>
        <span class="small-muted">Bot Setup configures symbols and parameters. Live Snapshot shows latest pulled prices. History and Performance track outcomes.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    s1, s2, s3 = st.columns(3)
    s1.markdown(f"**Last Worker Run (local)**  \n`{format_timestamp_in_timezone(state.get('last_run_at'), display_tz)}`")
    s2.markdown(f"**Latest Bar Pull (local)**  \n`{format_timestamp_in_timezone(state.get('last_bar_at'), display_tz)}`")
    s3.markdown(f"**Enabled Assets**  \n`{len([a for a in strategy_assets if a.get('enabled', True)])}`")

    bot_tab, snapshot_tab, history_tab, performance_tab, guide_tab = st.tabs(
        ["Bot Setup", "Live Snapshot", "History", "Performance", "Guide"]
    )

    with bot_tab:
        left, right = st.columns([0.72, 0.28], gap="large")
        with left:
            st.subheader("Asset Configuration")
            st.caption("Ticker format uses Yahoo symbols (example: `ZSP.TO`, `AAPL`, `MSFT`).")
            assets_df = pd.DataFrame(
                strategy_assets,
                columns=["symbol", "buy_rise_pct", "sell_drop_pct", "x_days", "reopt_days", "enabled", "reinit_params"],
            )
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
                    "enabled": st.column_config.CheckboxColumn("Run in live bot"),
                    "reinit_params": st.column_config.CheckboxColumn("Re-init from 1Y data"),
                },
            )
            with st.form("config_form"):
                c1, c2 = st.columns(2)
                with c1:
                    initial_cash = st.number_input(
                        "Initial cash per asset",
                        min_value=100.0,
                        value=float(config.get("initial_cash", 1000.0)),
                        step=100.0,
                        help="Each enabled asset starts with this same amount.",
                    )
                with c2:
                    alerts_enabled = st.checkbox("Email alerts enabled", value=bool(config.get("alerts_enabled", True)))
                save = st.form_submit_button("Save bot settings", use_container_width=True)
                if save:
                    clean_assets = edited_assets.copy()
                    default_suffix = ""
                    base_symbol = str(config.get("symbol", "")).strip().upper()
                    if "." in base_symbol:
                        default_suffix = "." + base_symbol.split(".", 1)[1]
                    clean_assets["symbol"] = clean_assets["symbol"].apply(lambda v: normalize_symbol(v, default_suffix=default_suffix))
                    clean_assets = clean_assets[clean_assets["symbol"] != ""]
                    clean_assets["buy_rise_pct"] = pd.to_numeric(clean_assets["buy_rise_pct"], errors="coerce")
                    clean_assets["sell_drop_pct"] = pd.to_numeric(clean_assets["sell_drop_pct"], errors="coerce")
                    clean_assets["x_days"] = pd.to_numeric(clean_assets["x_days"], errors="coerce")
                    clean_assets["reopt_days"] = pd.to_numeric(clean_assets["reopt_days"], errors="coerce")
                    if "enabled" not in clean_assets.columns:
                        clean_assets["enabled"] = True
                    clean_assets["enabled"] = clean_assets["enabled"].fillna(True).astype(bool)
                    if "reinit_params" not in clean_assets.columns:
                        clean_assets["reinit_params"] = False
                    clean_assets["reinit_params"] = clean_assets["reinit_params"].fillna(False).astype(bool)
                    if clean_assets.empty:
                        notify(False, "Add at least one asset before saving.")
                    else:
                        with st.spinner("Initializing missing parameters from 1Y hourly data..."):
                            clean_assets, init_notes = initialize_asset_params(clean_assets, initial_cash=float(initial_cash))
                        clean_assets["buy_rise_pct"] = pd.to_numeric(clean_assets["buy_rise_pct"], errors="coerce").fillna(1.0)
                        clean_assets["sell_drop_pct"] = pd.to_numeric(clean_assets["sell_drop_pct"], errors="coerce").fillna(1.5)
                        clean_assets["x_days"] = pd.to_numeric(clean_assets["x_days"], errors="coerce").fillna(20).astype(int)
                        clean_assets["reopt_days"] = pd.to_numeric(clean_assets["reopt_days"], errors="coerce").fillna(5).astype(int)
                        for note in init_notes:
                            st.caption(note)
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

        with right:
            st.subheader("Manual Trigger")
            if st.button("Run check now", use_container_width=True):
                ok, msg = trigger_workflow()
                notify(ok, msg)
            st.caption("Triggers one immediate pull and signal run.")
            st.markdown("---")
            st.subheader("Selected Asset Monitor")
            monitor_symbols = [str(a.get("symbol", "")).upper() for a in strategy_assets if str(a.get("symbol", "")).strip()]
            if monitor_symbols:
                selected_symbol = st.selectbox("Asset", options=monitor_symbols, key="monitor_symbol")
                selected_cfg = next((a for a in strategy_assets if str(a.get("symbol", "")).upper() == selected_symbol), {})
                asset_state = state.get("assets", {}).get(selected_symbol, {})
                st.metric("Buy rise %", f"{float(selected_cfg.get('buy_rise_pct', 0.0)):.3f}")
                st.metric("Sell drop %", f"{float(selected_cfg.get('sell_drop_pct', 0.0)):.3f}")
                st.metric("x days", str(int(selected_cfg.get("x_days", 0))))
                st.metric("Reopt every N days", str(int(selected_cfg.get("reopt_days", 0))))
                st.caption(f"Last action: {asset_state.get('last_action', 'N/A')}")
                st.caption(f"Last price: {asset_state.get('last_price', 'N/A')}")
            else:
                st.info("Add at least one asset to monitor.")

    with snapshot_tab:
        st.subheader("Live Price Snapshot")
        price_snapshot = build_price_snapshot(strategy_assets, state, display_tz)
        if price_snapshot.empty:
            st.info("No symbols configured yet. Add assets in Bot Setup.")
        else:
            st.dataframe(price_snapshot, use_container_width=True, hide_index=True)
            st.download_button(
                "Download snapshot CSV",
                data=price_snapshot.to_csv(index=False).encode("utf-8"),
                file_name="live_price_snapshot.csv",
                mime="text/csv",
            )

    with history_tab:
        st.subheader("Execution History")
        history_symbols = ["ALL"]
        if not trades.empty and "symbol" in trades.columns:
            history_symbols.extend(sorted(trades["symbol"].dropna().astype(str).unique().tolist()))
        selected_history_symbol = st.selectbox("Filter by symbol", options=history_symbols, key="history_symbol_filter")
        max_rows = st.slider("Rows", min_value=20, max_value=500, value=100, step=20)

        trades_view = trades.copy()
        params_view = params_hist.copy()
        if selected_history_symbol != "ALL":
            if "symbol" in trades_view.columns:
                trades_view = trades_view[trades_view["symbol"].astype(str) == selected_history_symbol]
            if "symbol" in params_view.columns:
                params_view = params_view[params_view["symbol"].astype(str) == selected_history_symbol]

        left, right = st.columns(2, gap="large")
        with left:
            st.subheader("Recent Trades")
            st.dataframe(trades_view.tail(max_rows), use_container_width=True, hide_index=True)
        with right:
            st.subheader("Recent Re-optimizations")
            st.dataframe(params_view.tail(max_rows), use_container_width=True, hide_index=True)
        st.subheader("Last Signal Reason")
        st.code(str(state.get("last_signal_reason", "No reason available")))

    with performance_tab:
        st.subheader("Performance Dashboard")
        if not equity.empty:
            equity["Datetime"] = pd.to_datetime(equity["Datetime"])
            perf_symbols = ["ALL"]
            if "symbol" in equity.columns:
                perf_symbols.extend(sorted(equity["symbol"].dropna().astype(str).unique().tolist()))
            selected_perf_symbol = st.selectbox("Equity symbol", options=perf_symbols, key="perf_symbol_filter")
            eq_view = equity.copy()
            if selected_perf_symbol != "ALL" and "symbol" in eq_view.columns:
                eq_view = eq_view[eq_view["symbol"].astype(str) == selected_perf_symbol]

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=eq_view["Datetime"], y=eq_view["Portfolio_Value"], mode="lines", name="Portfolio Value"))
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

            latest_val = float(eq_view["Portfolio_Value"].iloc[-1]) if not eq_view.empty else 0.0
            first_val = float(eq_view["Portfolio_Value"].iloc[0]) if not eq_view.empty else 0.0
            pnl = latest_val - first_val
            p1, p2, p3 = st.columns(3)
            p1.metric("Latest Value", f"{latest_val:,.2f}")
            p2.metric("Net P/L", f"{pnl:,.2f}")
            p3.metric("Data Points", str(len(eq_view)))
        else:
            st.info("No equity data yet.")

    with guide_tab:
        st.subheader("Operator Guide")
        st.markdown(
            """
            **Daily operating workflow**
            1. Open **Bot Setup** and verify enabled assets + thresholds.
            2. Click **Run check now** when you need an immediate run.
            3. Open **Live Snapshot** to verify pulled prices and timestamps.
            4. Use **History** to inspect trade and re-optimization outcomes.
            5. Review **Performance** for equity trend and P/L.

            **Important behavior**
            - Worker supports multiple enabled assets from the bot table.
            - Every enabled asset uses the same initial cash amount (per-asset setting).
            - `Re-init from 1Y data` is a one-time recalibration flag and resets after save.
            """
        )


if __name__ == "__main__":
    main()
