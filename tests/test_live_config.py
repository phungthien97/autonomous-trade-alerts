import pytest

from app.live import LiveConfig, bootstrap_live_state, load_live_config, parse_mode, save_live_config
from app.live.modes import TradingMode


def test_parse_modes() -> None:
    assert parse_mode("live") is TradingMode.live
    assert parse_mode("broker_paper") is TradingMode.broker_paper
    with pytest.raises(ValueError, match="Unknown trading mode"):
        parse_mode("paper")


def test_bootstrap_and_roundtrip(tmp_path) -> None:
    state_dir = tmp_path / "state_live"
    bootstrap_live_state(state_dir)
    assert (state_dir / "config.json").exists()
    assert (state_dir / "state.json").exists()
    assert (state_dir / "audit").is_dir()
    loaded = load_live_config(state_dir / "config.json")
    # Empty until picker apply (or active_selection present).
    assert loaded.symbols == []
    assert loaded.allow_fractional_default is False
    loaded.mode = TradingMode.broker_paper
    loaded.total_cash = 1500.0
    loaded.symbols = ["AAPL"]
    save_live_config(state_dir / "config.json", loaded)
    again = load_live_config(state_dir / "config.json")
    assert again.mode is TradingMode.broker_paper
    assert again.total_cash == 1500.0
    assert again.symbols == ["AAPL"]
    assert isinstance(again, LiveConfig)
