"""Safe controls only — no mode change API on the remote control surface."""

import inspect

import app.live.control as control
import app.remote.ui as ui


def test_live_control_module_has_safe_controls_only() -> None:
    assert hasattr(control, "enable_trading")
    assert hasattr(control, "disable_trading")
    assert hasattr(control, "ack_risk")
    assert hasattr(control, "live_status")
    assert not hasattr(control, "set_mode")
    assert not hasattr(control, "change_mode")


def test_remote_ui_imports_safe_controls_only() -> None:
    src = inspect.getsource(ui)
    assert "enable_trading" in src
    assert "disable_trading" in src
    assert "ack_risk" in src
    assert "set_mode" not in src
    assert "TradingMode" not in src
