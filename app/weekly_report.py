from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from app.notifier import send_signal_email
from app.paths import StatePaths, get_state_dir
from app.timezone_utils import DISPLAY_TZ, format_display, should_send_weekly_now


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def weeks_since(experiment_start: str | None, now: datetime | None = None) -> int:
    if not experiment_start:
        return 0
    now = now or datetime.now(timezone.utc)
    start = _parse_utc(experiment_start)
    if start is None:
        return 0
    return int((now.astimezone(timezone.utc) - start.astimezone(timezone.utc)).days // 7)


def _portfolio_return_since_start(
    equity: pd.DataFrame,
    initial_cash: float,
    symbols: list[str],
    experiment_start: str | None,
) -> float:
    if equity.empty or not symbols:
        return 0.0
    eq = equity.copy()
    eq["Datetime"] = pd.to_datetime(eq["Datetime"], utc=True, errors="coerce")
    start_dt = _parse_utc(experiment_start)
    if start_dt is not None:
        eq = eq[eq["Datetime"] >= start_dt]
    if eq.empty:
        return 0.0

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
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_et = now_utc.astimezone(DISPLAY_TZ)
    period_start = now_utc - timedelta(days=7)

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
    experiment_start = v1_config.get("experiment_start") or v2_config.get("experiment_start")

    v1_trades_week = _period_slice(v1_trades, period_start, now_utc)
    v2_trades_week = _period_slice(v2_trades, period_start, now_utc)
    v2_params_week = _period_slice(v2_params, period_start, now_utc) if not v2_params.empty else v2_params

    v1_since = _portfolio_return_since_start(v1_equity, initial_cash, symbols, experiment_start)
    v2_since = _portfolio_return_since_start(v2_equity, initial_cash, symbols, experiment_start)

    exp_start_et = format_display(_parse_utc(str(experiment_start))) if experiment_start else "not set"
    lines = [
        "Weekly Trading Bot Summary",
        f"Period: {format_display(period_start.astimezone(DISPLAY_TZ))} to {format_display(now_et)}",
        f"Experiment start (ET): {exp_start_et}",
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

    start_dt = _parse_utc(str(experiment_start)) if experiment_start else None
    lines.extend(["", "Per-symbol latest values:"])
    for symbol in symbols:
        v1_sym = v1_equity[v1_equity["symbol"].astype(str) == symbol] if not v1_equity.empty and "symbol" in v1_equity.columns else pd.DataFrame()
        v2_sym = v2_equity[v2_equity["symbol"].astype(str) == symbol] if not v2_equity.empty and "symbol" in v2_equity.columns else pd.DataFrame()
        if start_dt is not None and not v1_sym.empty:
            v1_sym = v1_sym[pd.to_datetime(v1_sym["Datetime"], utc=True) >= start_dt]
        if start_dt is not None and not v2_sym.empty:
            v2_sym = v2_sym[pd.to_datetime(v2_sym["Datetime"], utc=True) >= start_dt]
        v1_val = float(v1_sym.sort_values("Datetime").iloc[-1]["Portfolio_Value"]) if not v1_sym.empty else initial_cash
        v2_val = float(v2_sym.sort_values("Datetime").iloc[-1]["Portfolio_Value"]) if not v2_sym.empty else initial_cash
        lines.append(f"  {symbol}: V1={v1_val:,.2f}  V2={v2_val:,.2f}")

    leader = "V1" if v1_since >= v2_since else "V2"
    margin = abs(v1_since - v2_since)
    lines.extend(
        [
            "",
            f"Leader since experiment start: {leader} by {margin:.2f}%",
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
    experiment_start = v1_config.get("experiment_start") or v2_config.get("experiment_start")
    v1_since = _portfolio_return_since_start(v1_equity, initial_cash, symbols, experiment_start)
    v2_since = _portfolio_return_since_start(v2_equity, initial_cash, symbols, experiment_start)
    leader = "V1" if v1_since >= v2_since else "V2"
    margin = abs(v1_since - v2_since)
    weeks = weeks_since(experiment_start, now=now)
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
    experiment_start = v2_config.get("experiment_start")
    week = weeks_since(experiment_start, now=now)
    if week >= experiment_weeks:
        return build_conclusion_report(project_root=root, now=now)
    return build_weekly_report(project_root=root, now=now)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and optionally send weekly bot summary.")
    parser.add_argument("--dry-run", action="store_true", help="Print report without sending email")
    parser.add_argument("--send", action="store_true", help="Send report via email")
    parser.add_argument("--force", action="store_true", help="Send even if not Saturday 10:00 AM ET")
    args = parser.parse_args()

    if args.send and not args.force and not args.dry_run and not should_send_weekly_now():
        print("weekly_email=skipped reason=not_saturday_10am_eastern")
        return

    report = build_report()
    print(report)
    if args.send and not args.dry_run:
        send_signal_email(
            subject="Weekly Trading Bot Summary",
            body=report,
        )


if __name__ == "__main__":
    main()
