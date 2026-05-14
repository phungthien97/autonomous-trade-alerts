from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


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
    msg.set_content(body)

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
