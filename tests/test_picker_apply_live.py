import json
from pathlib import Path

from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.modes import TradingMode
from app.picker.apply_live import apply_to_live_config
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
