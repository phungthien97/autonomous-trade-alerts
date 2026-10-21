import json
from pathlib import Path

from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.modes import TradingMode
from app.picker.apply_live import apply_allocated_cash_to_live_state, apply_to_live_config
from app.picker.pending import PendingSymbol


def test_apply_to_live_config_updates_symbols_preserves_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "state_live" / "config.json"
    save_live_config(
        config_path,
        LiveConfig(
            mode=TradingMode.broker_paper,
            symbols=["MSFT", "AAPL", "SMH"],
            trading_enabled=True,
            total_cash=1000.0,
            assets=[SymbolParams("MSFT"), SymbolParams("AAPL"), SymbolParams("SMH")],
        ),
    )
    apply_to_live_config(
        config_path,
        [
            PendingSymbol("NVDA", buy_rise=0.025, sell_drop=0.04, edge=0.1, strategy_return=0.2),
            PendingSymbol("AAPL", buy_rise=0.01, sell_drop=0.02, edge=0.05, strategy_return=0.1),
        ],
        extra_symbols=["MSFT"],
    )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["mode"] == "broker_paper"
    assert raw["trading_enabled"] is True
    assert raw["symbols"] == ["NVDA", "AAPL", "MSFT"]
    by_sym = {a["symbol"]: a for a in raw["assets"]}
    assert by_sym["NVDA"]["buy_rise_pct"] == 2.5
    assert by_sym["AAPL"]["sell_drop_pct"] == 2.0


def test_apply_allocated_cash_to_live_state_sets_flat_sleeves(tmp_path: Path) -> None:
    state_path = tmp_path / "state_live" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "assets": {
                    "P": {"cash": 600.0, "shares": 0.0, "peak": None, "trough": 100.0},
                    "HELD": {"cash": 0.0, "shares": 2.0, "peak": 10.0, "trough": None},
                },
                "cash_usd": 3000.0,
            }
        ),
        encoding="utf-8",
    )
    apply_allocated_cash_to_live_state(
        state_path,
        [
            PendingSymbol(
                "P",
                buy_rise=0.01,
                sell_drop=0.02,
                edge=0.1,
                strategy_return=0.2,
                allocated_cash=800.0,
            ),
            PendingSymbol(
                "NEW",
                buy_rise=0.01,
                sell_drop=0.02,
                edge=0.1,
                strategy_return=0.1,
                allocated_cash=500.0,
            ),
            PendingSymbol(
                "HELD",
                buy_rise=0.01,
                sell_drop=0.02,
                edge=0.1,
                strategy_return=0.05,
                allocated_cash=900.0,
            ),
        ],
    )
    assets = json.loads(state_path.read_text(encoding="utf-8"))["assets"]
    assert assets["P"]["cash"] == 800.0
    assert assets["NEW"]["cash"] == 500.0
    assert assets["HELD"]["cash"] == 0.0  # already long — unchanged
    assert assets["HELD"]["shares"] == 2.0
