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

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(user, app_password)
        server.send_message(msg)
    return True
