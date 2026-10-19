from app.picker.rank import select_symbols


def test_select_symbols_ranks_by_strategy_profit_with_edge_floor() -> None:
    """Hybrid B: edge >= 0 and strategy >= 0; rank by strategy_return."""
    rows = [
        # High edge but tiny profit — should rank below bigger profits
        {"symbol": "COHR", "edge": 0.25, "strategy_return": 0.01, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        # Negative edge despite big profit — excluded
        {"symbol": "MRNA", "edge": -0.20, "strategy_return": 0.50, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        # Negative strategy despite positive edge (SKYD-style) — excluded
        {"symbol": "SKYD", "edge": 0.23, "strategy_return": -0.09, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "P", "edge": 0.10, "strategy_return": 0.29, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "FICO", "edge": 0.35, "strategy_return": 0.16, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "HUM", "edge": 0.06, "strategy_return": 0.15, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "AMGN", "edge": 0.01, "strategy_return": 0.14, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "VLO", "edge": 0.05, "strategy_return": 0.12, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "SKIP", "edge": 0.40, "strategy_return": 0.99, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": True},
    ]
    selected = select_symbols(rows, max_n=5)
    assert [s.symbol for s in selected] == ["P", "FICO", "HUM", "AMGN", "VLO"]
    assert all(s.edge >= 0 and s.strategy_return >= 0 for s in selected)


def test_select_symbols_all_negative_edge_returns_empty() -> None:
    rows = [
        {"symbol": "X", "edge": -0.1, "strategy_return": 0.5, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "Y", "edge": -0.2, "strategy_return": 0.4, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
    ]
    assert select_symbols(rows) == []


def test_select_symbols_negative_strategy_excluded_even_with_edge() -> None:
    rows = [
        {"symbol": "SKYD", "edge": 0.23, "strategy_return": -0.09, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
        {"symbol": "FICO", "edge": 0.35, "strategy_return": 0.16, "buy_rise": 0.02, "sell_drop": 0.03, "skipped": False},
    ]
    selected = select_symbols(rows, max_n=5)
    assert [s.symbol for s in selected] == ["FICO"]


def test_select_symbols_tie_break_edge_then_symbol() -> None:
    rows = [
        {"symbol": "BB", "edge": 0.05, "strategy_return": 0.2, "buy_rise": 0.01, "sell_drop": 0.02, "skipped": False},
        {"symbol": "AA", "edge": 0.10, "strategy_return": 0.2, "buy_rise": 0.01, "sell_drop": 0.02, "skipped": False},
        {"symbol": "CC", "edge": 0.01, "strategy_return": 0.2, "buy_rise": 0.01, "sell_drop": 0.02, "skipped": False},
    ]
    selected = select_symbols(rows, max_n=3)
    # Same strategy_return → higher edge first, then alphabetical
    assert [s.symbol for s in selected] == ["AA", "BB", "CC"]
