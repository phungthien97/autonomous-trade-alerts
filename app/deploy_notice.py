from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.notifier import send_signal_email
from app.paths import ROOT, StatePaths
from app.timezone_utils import format_display, now_display


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_go_live_message(project_root: Path | None = None) -> str:
    root = project_root or ROOT
    v1_paths = StatePaths("v1", project_root=root)
    v2_paths = StatePaths("v2", project_root=root)
    v1_config = _read_json(v1_paths.config_path)
    v2_config = _read_json(v2_paths.config_path)
    now = now_display()

    symbols = [
        str(a.get("symbol", "")).upper()
        for a in v1_config.get("assets", [])
        if a.get("enabled", True) and str(a.get("symbol", "")).strip()
    ]
    experiment_start = v2_config.get("experiment_start", "not set")
    experiment_weeks = v2_config.get("experiment_weeks", 10)

    return "\n".join(
        [
            "V2 Experiment is LIVE",
            "",
            f"Deployed at (ET): {format_display(now)}",
            f"Experiment start: {experiment_start}",
            f"Duration: {experiment_weeks} weeks",
            "",
            "What is running:",
            "  - V1 worker every 10 min -> state/ (original optimizer, unchanged)",
            "  - V2 worker every 10 min -> state_v2/ (constrained optimizer + holdout)",
            "  - Weekly summary email: Saturdays 10:00 AM Eastern Time",
            "  - Conclusion email: week 10",
            "",
            f"Symbols ({len(symbols)}): {', '.join(symbols)}",
            f"Per-asset capital: ${float(v1_config.get('initial_cash', 1000.0)):,.0f}",
            "",
            "Per-trade alerts: OFF for both versions",
            "",
            "Dashboard: use the Compare tab to track V1 vs V2 side by side.",
            "",
            "You will get a weekly email every Saturday. No action needed until then.",
        ]
    )


def send_go_live_if_needed(project_root: Path | None = None, force: bool = False) -> bool:
    root = project_root or ROOT
    flag_path = StatePaths("v2", project_root=root).state_dir / "go_live_sent.json"
    if flag_path.exists() and not force:
        return False

    body = build_go_live_message(project_root=root)
    sent = send_signal_email(subject="[LIVE] V1 + V2 trading experiment started", body=body)
    if not sent:
        print("go_live_email=skipped reason=missing_smtp_credentials")
        return False

    _write_json(
        flag_path,
        {
            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "subject": "[LIVE] V1 + V2 trading experiment started",
        },
    )
    print("go_live_email=sent")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one-time go-live notification email.")
    parser.add_argument("--if-needed", action="store_true", help="Send only if not sent before")
    parser.add_argument("--force", action="store_true", help="Send even if already sent")
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending")
    args = parser.parse_args()

    if args.dry_run:
        print(build_go_live_message())
        return

    if args.if_needed:
        send_go_live_if_needed(force=args.force)
        return

    body = build_go_live_message()
    if args.force or not (StatePaths("v2").state_dir / "go_live_sent.json").exists():
        send_signal_email(subject="[LIVE] V1 + V2 trading experiment started", body=body)
    else:
        print("go_live_email=already_sent")


if __name__ == "__main__":
    main()
