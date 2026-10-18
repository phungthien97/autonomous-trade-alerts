from app.picker.rank import select_symbols


def test_select_symbols_keeps_nonnegative_and_caps() -> None:
    rows = [
        {"symbol": "A", "edge": 0.10, "strategy_return": 0.2, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "B", "edge": -0.01, "strategy_return": 0.5, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "C", "edge": 0.05, "strategy_return": 0.1, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "D", "edge": 0.08, "strategy_return": 0.15, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": True},
        {"symbol": "E", "edge": 0.04, "strategy_return": 0.12, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "F", "edge": 0.03, "strategy_return": 0.11, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "G", "edge": 0.02, "strategy_return": 0.10, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "H", "edge": 0.01, "strategy_return": 0.09, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
    ]
    selected = select_symbols(rows, max_n=5)
    assert [s.symbol for s in selected] == ["A", "C", "E", "F", "G"]
    assert all(s.edge >= 0 for s in selected)


def test_select_symbols_all_negative_returns_empty() -> None:
    rows = [
        {"symbol": "X", "edge": -0.1, "strategy_return": 0.0, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "Y", "edge": -0.2, "strategy_return": 0.0, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
    ]
    assert select_symbols(rows) == []


def test_select_symbols_tie_break_deterministic() -> None:
    rows = [
        {"symbol": "BB", "edge": 0.1, "strategy_return": 0.2, "buy_rise": 0.01, "sell_drop": 0.02, "skipped": False},
        {"symbol": "AA", "edge": 0.1, "strategy_return": 0.2, "buy_rise": 0.01, "sell_drop": 0.02, "skipped": False},
        {"symbol": "CC", "edge": 0.1, "strategy_return": 0.3, "buy_rise": 0.01, "sell_drop": 0.02, "skipped": False},
    ]
    selected = select_symbols(rows, max_n=3)
    assert [s.symbol for s in selected] == ["CC", "AA", "BB"]
