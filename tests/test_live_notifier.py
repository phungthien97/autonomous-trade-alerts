from datetime import datetime
from zoneinfo import ZoneInfo

from app.notifier import (
    clear_alert_cooldown,
    format_eastern_now,
    notify_fill,
    notify_live_event,
    send_live_event_email,
    send_signal_email,
)


def test_fill_subject(monkeypatch) -> None:
    seen = {}

    def fake_send(subject, body):
        seen["subject"] = subject
        seen["body"] = body
        return True

    monkeypatch.setattr("app.notifier.send_signal_email", fake_send)
    assert notify_fill("AAPL 1 share") is True
    assert "FILL" in seen["subject"]


def test_flag_can_disable_fill(monkeypatch) -> None:
    called = {"n": 0}
    monkeypatch.setattr("app.notifier.send_signal_email", lambda subject, body: called.__setitem__("n", called["n"] + 1) or True)
    assert notify_live_event("fill", "body", {"fill": False}) is False
    assert called["n"] == 0


def test_send_live_event_reuses_gmail(monkeypatch) -> None:
    monkeypatch.setattr("app.notifier.send_signal_email", lambda subject, body: subject == "Hello" and body == "There")
    assert send_live_event_email("Hello", "There") is True


def test_format_eastern_now_uses_toronto() -> None:
    winter = datetime(2026, 1, 15, 17, 0, 0, tzinfo=ZoneInfo("UTC"))
    summer = datetime(2026, 7, 15, 16, 0, 0, tzinfo=ZoneInfo("UTC"))
    assert format_eastern_now(winter).endswith("EST")
    assert "12:00:00 PM" in format_eastern_now(winter)
    assert format_eastern_now(summer).endswith("EDT")


def test_disconnect_cooldown_suppresses_repeats(monkeypatch, tmp_path) -> None:
    cool = tmp_path / "cooldown.json"
    monkeypatch.setenv("ALERT_COOLDOWN_PATH", str(cool))
    sent = {"n": 0}

    def fake_send(subject, body):
        sent["n"] += 1
        return True

    monkeypatch.setattr("app.notifier.send_signal_email", fake_send)
    assert notify_live_event("disconnect", "down1") is True
    assert notify_live_event("disconnect", "down2") is False
    assert sent["n"] == 1
    clear_alert_cooldown("disconnect")
    assert notify_live_event("disconnect", "down3") is True
    assert sent["n"] == 2


def test_send_signal_email_body_gets_eastern_stamp(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_USER", "a@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")
    monkeypatch.setenv("ALERT_TO_EMAIL", "b@example.com")
    captured = {}

    class _FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            return None

        def login(self, user, password):
            return None

        def send_message(self, msg):
            captured["body"] = msg.get_content()

    monkeypatch.setattr("app.notifier.smtplib.SMTP", _FakeSMTP)
    assert send_signal_email("Hello", "There") is True
    assert captured["body"].startswith("Time:")
    assert "EST" in captured["body"] or "EDT" in captured["body"]
    assert "There" in captured["body"]
    assert "Z" not in captured["body"].split("\n", 1)[0]
