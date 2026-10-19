from __future__ import annotations

import json
import os
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/Toronto")

# Seconds between repeat emails for noisy kinds (disconnect every 5m cycle).
_ALERT_COOLDOWN_SEC = {
    "disconnect": 6 * 3600,  # one email per outage window
    "weekly_2fa": 6 * 3600,
}


def format_eastern_now(when: datetime | None = None) -> str:
    """Wall-clock time in Eastern (EST/EDT) for email bodies."""
    moment = when or datetime.now(tz=EASTERN)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC")).astimezone(EASTERN)
    else:
        moment = moment.astimezone(EASTERN)
    # e.g. 2026-10-07 08:15:02 PM EDT
    return moment.strftime("%Y-%m-%d %I:%M:%S %p %Z")


def _with_eastern_timestamp(body: str) -> str:
    """Append Eastern wall-clock as a footer so the headline stays first."""
    stamp = format_eastern_now()
    text = (body or "").rstrip()
    if not text:
        return f"—\nSent: {stamp}\n"
    last = text.splitlines()[-1]
    if last.startswith("Sent:") or last.startswith("Time:"):
        return text + "\n"
    if text.startswith("Time:"):
        # Legacy bodies that already stamped at the top — leave unchanged.
        return text + "\n"
    return f"{text}\n\n—\nSent: {stamp}\n"


def send_signal_email(subject: str, body: str) -> bool:
    user = os.getenv("GMAIL_USER")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("ALERT_TO_EMAIL")
    if not user or not app_password or not recipient:
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content(_with_eastern_timestamp(body))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(user, app_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        err = getattr(e, "smtp_error", b"") or b""
        if getattr(e, "smtp_code", None) == 534 and b"Application-specific password" in err:
            raise RuntimeError(
                "Gmail SMTP login failed: use a Google App Password in GitHub secret "
                "GMAIL_APP_PASSWORD (16 characters, no spaces), not your normal Gmail password. "
                "Requires 2-Step Verification: https://myaccount.google.com/apppasswords"
            ) from e
        raise
    return True


DEFAULT_ALERT_FLAGS = {
    "fill": True,
    "reject": True,
    "disconnect": True,
    "risk_alert": True,
    "trading_stopped": True,
    "weekly_2fa": True,
    "picker_applied": True,
    "picker_stale": True,
}

_SUBJECTS = {
    "fill": "[LIVE] Trade filled",
    "reject": "[LIVE] Order rejected",
    "disconnect": "[LIVE] Broker disconnected",
    "risk_alert": "[LIVE] Needs attention",
    "trading_stopped": "[LIVE] Trading stopped",
    "weekly_2fa": "[LIVE] Weekly 2FA required",
    "picker_applied": "[PICKER] New sleeves applied",
    "picker_stale": "[PICKER] Pending not applied",
}


def send_live_event_email(subject: str, body: str) -> bool:
    return send_signal_email(subject, body)


def alert_cooldown_path() -> Path:
    override = os.environ.get("ALERT_COOLDOWN_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "state_live" / "alert_cooldown.json"


def clear_alert_cooldown(kind: str, path: Path | None = None) -> None:
    """Clear cooldown after recovery so the next outage can alert again."""
    store = path or alert_cooldown_path()
    if not store.is_file():
        return
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if kind not in data:
        return
    data.pop(kind, None)
    store.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _cooldown_blocks(kind: str, path: Path | None = None) -> bool:
    sec = _ALERT_COOLDOWN_SEC.get(kind)
    if not sec:
        return False
    store = path or alert_cooldown_path()
    try:
        data = json.loads(store.read_text(encoding="utf-8")) if store.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    last = float(data.get(kind, 0) or 0)
    now = time.time()
    if last and (now - last) < sec:
        return True
    data[kind] = now
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return False


def notify_live_event(kind: str, body: str, flags: dict | None = None) -> bool:
    enabled = DEFAULT_ALERT_FLAGS if flags is None else {**DEFAULT_ALERT_FLAGS, **flags}
    if not enabled.get(kind, False):
        return False
    if _cooldown_blocks(kind):
        print(f"alert_cooldown kind={kind} skipped_repeat_email")
        return False
    subject = _SUBJECTS.get(kind, f"Live {kind}")
    return send_live_event_email(subject, body)


def notify_fill(body: str, flags: dict | None = None) -> bool:
    return notify_live_event("fill", body, flags)


def notify_reject(body: str, flags: dict | None = None) -> bool:
    return notify_live_event("reject", body, flags)


def notify_disconnect(body: str, flags: dict | None = None) -> bool:
    return notify_live_event("disconnect", body, flags)


def notify_risk_alert(body: str, flags: dict | None = None) -> bool:
    return notify_live_event("risk_alert", body, flags)


def notify_trading_stopped(body: str, flags: dict | None = None) -> bool:
    return notify_live_event("trading_stopped", body, flags)


def notify_weekly_2fa_required(body: str, flags: dict | None = None) -> bool:
    return notify_live_event("weekly_2fa", body, flags)
