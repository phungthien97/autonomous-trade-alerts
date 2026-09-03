from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.notifier import send_signal_email
from app.paths import StatePaths, get_state_dir


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def weeks_since(experiment_start: str | None, now: datetime | None = None) -> int:
    if not experiment_start:
        return 0
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(str(experiment_start).replace("Z", "+00:00"))
    return int((now - start).days // 7)


def _portfolio_return(equity: pd.DataFrame, initial_cash: float, symbols: list[str]) -> float:
    if equity.empty or not symbols:
        return 0.0
    eq = equity.copy()
    if "Datetime" in eq.columns:
        eq["Datetime"] = pd.to_datetime(eq["Datetime"], utc=True, errors="coerce")
    total_latest = 0.0
    for symbol in symbols:
        sym_eq = eq[eq["symbol"].astype(str) == symbol] if "symbol" in eq.columns else eq
        if sym_eq.empty:
            total_latest += initial_cash
        else:
            total_latest += float(sym_eq.sort_values("Datetime").iloc[-1]["Portfolio_Value"])
    invested = initial_cash * len(symbols)
    if invested <= 0:
        return 0.0
    return (total_latest / invested - 1.0) * 100.0


def _period_slice(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    if df.empty or "Datetime" not in df.columns:
        return df
    out = df.copy()
    out["Datetime"] = pd.to_datetime(out["Datetime"], utc=True, errors="coerce")
    return out[(out["Datetime"] >= start) & (out["Datetime"] < end)]


def build_weekly_report(
    project_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    root = project_root or Path(__file__).resolve().parents[1]
    now = now or datetime.now(timezone.utc)
    period_start = now - timedelta(days=7)

    v1_paths = StatePaths("v1", project_root=root)
    v2_paths = StatePaths("v2", project_root=root)
    v1_config = _read_json(v1_paths.config_path)
    v2_config = _read_json(v2_paths.config_path)
    v1_equity = _read_csv(v1_paths.equity_path)
    v2_equity = _read_csv(v2_paths.equity_path)
    v1_trades = _read_csv(v1_paths.trades_path)
    v2_trades = _read_csv(v2_paths.trades_path)
    v2_params = _read_csv(v2_paths.params_path)

    symbols = [
        str(a.get("symbol", "")).upper()
        for a in v1_config.get("assets", [])
        if a.get("enabled", True) and str(a.get("symbol", "")).strip()
    ]
    initial_cash = float(v1_config.get("initial_cash", 1000.0))
    experiment_start = v2_config.get("experiment_start")

    v1_week = _period_slice(v1_equity, period_start, now)
    v2_week = _period_slice(v2_equity, period_start, now)
    v1_trades_week = _period_slice(v1_trades, period_start, now)
    v2_trades_week = _period_slice(v2_trades, period_start, now)
    v2_params_week = _period_slice(v2_params, period_start, now) if not v2_params.empty else v2_params

    v1_since = _portfolio_return(v1_equity, initial_cash, symbols)
    v2_since = _portfolio_return(v2_equity, initial_cash, symbols)

    lines = [
        "Weekly Trading Bot Summary",
        f"Period: {period_start.date()} to {now.date()} (UTC)",
        "",
        "Portfolio return since experiment start:",
        f"  V1: {v1_since:+.2f}%",
        f"  V2: {v2_since:+.2f}%",
        "",
        "Trades this week:",
        f"  V1: {len(v1_trades_week)}",
        f"  V2: {len(v2_trades_week)}",
        "",
        "V2 re-optimizations this week:",
    ]
    if v2_params_week.empty:
        lines.append("  (none)")
    else:
        for _, row in v2_params_week.iterrows():
            status = row.get("status", "unknown")
            lines.append(
                f"  {row.get('symbol')}: {status} "
                f"buy={row.get('buy_rise_pct')}% sell={row.get('sell_drop_pct')}%"
            )

    lines.extend(["", "Per-symbol latest values:"])
    for symbol in symbols:
        v1_sym = v1_equity[v1_equity["symbol"].astype(str) == symbol] if not v1_equity.empty and "symbol" in v1_equity.columns else pd.DataFrame()
        v2_sym = v2_equity[v2_equity["symbol"].astype(str) == symbol] if not v2_equity.empty and "symbol" in v2_equity.columns else pd.DataFrame()
        v1_val = float(v1_sym.sort_values("Datetime").iloc[-1]["Portfolio_Value"]) if not v1_sym.empty else initial_cash
        v2_val = float(v2_sym.sort_values("Datetime").iloc[-1]["Portfolio_Value"]) if not v2_sym.empty else initial_cash
        lines.append(f"  {symbol}: V1={v1_val:,.2f}  V2={v2_val:,.2f}")

    leader = "V1" if v1_since >= v2_since else "V2"
    margin = abs(v1_since - v2_since)
    lines.extend(
        [
            "",
            f"Leader since {experiment_start or 'start'}: {leader} by {margin:.2f}%",
        ]
    )
    return "\n".join(lines)


def build_conclusion_report(
    project_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    weekly = build_weekly_report(project_root=project_root, now=now)
    root = project_root or Path(__file__).resolve().parents[1]
    v1_paths = StatePaths("v1", project_root=root)
    v2_paths = StatePaths("v2", project_root=root)
    v1_config = _read_json(v1_paths.config_path)
    v2_config = _read_json(v2_paths.config_path)
    v1_equity = _read_csv(v1_paths.equity_path)
    v2_equity = _read_csv(v2_paths.equity_path)
    symbols = [
        str(a.get("symbol", "")).upper()
        for a in v1_config.get("assets", [])
        if a.get("enabled", True) and str(a.get("symbol", "")).strip()
    ]
    initial_cash = float(v1_config.get("initial_cash", 1000.0))
    v1_since = _portfolio_return(v1_equity, initial_cash, symbols)
    v2_since = _portfolio_return(v2_equity, initial_cash, symbols)
    leader = "V1" if v1_since >= v2_since else "V2"
    margin = abs(v1_since - v2_since)
    weeks = weeks_since(v2_config.get("experiment_start"), now=now)
    conclusion = (
        f"\n\n=== 10-Week Conclusion (week {weeks}) ===\n"
        f"Winner: {leader} by {margin:.2f}% portfolio return since experiment start.\n"
        f"V1 total return: {v1_since:+.2f}% | V2 total return: {v2_since:+.2f}%"
    )
    return weekly.replace("Weekly Trading Bot Summary", "10-Week Experiment Conclusion") + conclusion


def build_report(
    project_root: Path | None = None,
    now: datetime | None = None,
) -> str:
    root = project_root or Path(__file__).resolve().parents[1]
    v2_config = _read_json(get_state_dir("v2", root) / "config.json")
    experiment_weeks = int(v2_config.get("experiment_weeks", 10))
    week = weeks_since(v2_config.get("experiment_start"), now=now)
    if week >= experiment_weeks:
        return build_conclusion_report(project_root=root, now=now)
    return build_weekly_report(project_root=root, now=now)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and optionally send weekly bot summary.")
    parser.add_argument("--dry-run", action="store_true", help="Print report without sending email")
    parser.add_argument("--send", action="store_true", help="Send report via email")
    args = parser.parse_args()
    report = build_report()
    print(report)
    if args.send and not args.dry_run:
        send_signal_email(
            subject="Weekly Trading Bot Summary",
            body=report,
        )


if __name__ == "__main__":
    main()
