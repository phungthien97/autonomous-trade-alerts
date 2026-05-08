from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

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


def main() -> None:
    st.set_page_config(page_title="Trade Signal Dashboard", layout="wide")
    st.title("Autonomous Buy/Sell Signal Dashboard")

    config = read_json(CONFIG_PATH)
    state = read_json(STATE_PATH)
    trades = read_csv_or_empty(TRADES_PATH)
    equity = read_csv_or_empty(EQUITY_PATH)
    params_hist = read_csv_or_empty(PARAMS_PATH)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Symbol", config["symbol"])
    c2.metric("Last Action", state.get("last_action", "N/A"))
    c3.metric("Portfolio Value", f"{float(state.get('cash', 0.0) + state.get('shares', 0.0) * state.get('last_price', 0.0)):.2f}")
    c4.metric("Last Run", state.get("last_run_at", "Never"))

    st.subheader("Config")
    with st.form("config_form"):
        symbol = st.text_input("Ticker", value=str(config["symbol"]).upper()).strip().upper()
        buy_rise_pct = st.number_input("Buy rise %", min_value=0.1, max_value=30.0, value=float(config["buy_rise_pct"]), step=0.1)
        sell_drop_pct = st.number_input("Sell drop %", min_value=0.1, max_value=30.0, value=float(config["sell_drop_pct"]), step=0.1)
        x_days = st.number_input("Trailing x days for re-optimization", min_value=5, max_value=365, value=int(config["x_days"]), step=1)
        reopt_days = st.number_input("Re-optimize every N days", min_value=1, max_value=30, value=int(config["reopt_days"]), step=1)
        alerts_enabled = st.checkbox("Email alerts enabled", value=bool(config.get("alerts_enabled", True)))
        save = st.form_submit_button("Save settings")
        if save:
            config.update(
                {
                    "symbol": symbol,
                    "buy_rise_pct": float(buy_rise_pct),
                    "sell_drop_pct": float(sell_drop_pct),
                    "x_days": int(x_days),
                    "reopt_days": int(reopt_days),
                    "alerts_enabled": bool(alerts_enabled),
                }
            )
            write_json(CONFIG_PATH, config)
            ok, msg = commit_file_to_github(CONFIG_PATH, "Update trading config from dashboard")
            st.success(msg) if ok else st.warning(msg)

    if st.button("Run check now"):
        ok, msg = trigger_workflow()
        st.success(msg) if ok else st.warning(msg)

    st.subheader("Equity Curve")
    if not equity.empty:
        equity["Datetime"] = pd.to_datetime(equity["Datetime"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity["Datetime"], y=equity["Portfolio_Value"], mode="lines", name="Portfolio Value"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No equity data yet.")

    left, right = st.columns(2)
    with left:
        st.subheader("Recent Trades")
        st.dataframe(trades.tail(50), use_container_width=True)
    with right:
        st.subheader("Recent Re-optimizations")
        st.dataframe(params_hist.tail(50), use_container_width=True)


if __name__ == "__main__":
    main()
