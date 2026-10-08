from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/Toronto")


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
    stamp = format_eastern_now()
    text = body or ""
    if text.startswith("Time:"):
        return text
    return f"Time: {stamp}\n\n{text}"


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
}

_SUBJECTS = {
    "fill": "Live FILL",
    "reject": "Live order REJECTED",
    "disconnect": "Live broker DISCONNECT",
    "risk_alert": "Live RISK alert",
    "trading_stopped": "Live trading STOPPED",
    "weekly_2fa": "Live weekly 2FA required",
}


def send_live_event_email(subject: str, body: str) -> bool:
    return send_signal_email(subject, body)


def notify_live_event(kind: str, body: str, flags: dict | None = None) -> bool:
    enabled = DEFAULT_ALERT_FLAGS if flags is None else {**DEFAULT_ALERT_FLAGS, **flags}
    if not enabled.get(kind, False):
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
