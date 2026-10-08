from datetime import datetime, timedelta, timezone

from app.risk import RiskController


def test_tick_before_two_hours_stays_enabled(tmp_path) -> None:
    ctl = RiskController(tmp_path / "risk.json")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    ctl.trigger("max_orders", now)
    assert ctl.tick(now + timedelta(hours=1)) is False
    assert ctl.trading_enabled is True


def test_tick_after_two_hours_disables(tmp_path) -> None:
    ctl = RiskController(tmp_path / "risk.json")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    ctl.trigger("disconnect", now)
    assert ctl.tick(now + timedelta(hours=2)) is True
    assert ctl.trading_enabled is False


def test_ack_prevents_disable(tmp_path) -> None:
    ctl = RiskController(tmp_path / "risk.json")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    ctl.trigger("reject", now)
    ctl.ack(now + timedelta(minutes=5))
    assert ctl.tick(now + timedelta(hours=3)) is False
    assert ctl.trading_enabled is True


def test_enable_after_stop(tmp_path) -> None:
    ctl = RiskController(tmp_path / "risk.json")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    ctl.trigger("dd", now)
    ctl.tick(now + timedelta(hours=2))
    ctl.enable()
    assert ctl.trading_enabled is True
