import json
from pathlib import Path

from app.picker.apply_paper import apply_to_paper_v1
from app.picker.pending import PendingSymbol


def test_apply_to_paper_v1_updates_assets_and_state(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    config_path.write_text(
        json.dumps(
            {
                "initial_cash": 1000.0,
                "x_days": 20,
                "reopt_days": 5,
                "assets": [
                    {
                        "symbol": "MSFT",
                        "buy_rise_pct": 1.0,
                        "sell_drop_pct": 2.0,
                        "x_days": 20,
                        "reopt_days": 5,
                        "enabled": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "assets": {
                    "MSFT": {
                        "cash": 0.0,
                        "shares": 2.0,
                        "peak": 100.0,
                        "trough": None,
                        "initial_cash": 1000.0,
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    apply_to_paper_v1(
        config_path,
        state_path,
        [PendingSymbol("AAPL", 0.02, 0.03, 0.1, 0.2, 0.1)],
        exit_only_symbols=["MSFT"],
        awaiting_first_buy=["AAPL"],
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    symbols = [a["symbol"] for a in config["assets"]]
    assert symbols == ["AAPL", "MSFT"]
    by_sym = {a["symbol"]: a for a in config["assets"]}
    assert by_sym["AAPL"]["buy_rise_pct"] == 2.0
    assert by_sym["AAPL"]["awaiting_first_buy"] is True
    assert by_sym["MSFT"]["exit_only"] is True
    assert state["assets"]["AAPL"]["awaiting_first_buy"] is True
    assert state["assets"]["MSFT"]["exit_only"] is True
    assert state["assets"]["MSFT"]["shares"] == 2.0
