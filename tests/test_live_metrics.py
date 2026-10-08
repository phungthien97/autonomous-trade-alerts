from app.live import equal_weight_bh_value, returns_from_values


def test_bot_beats_and_loses_buy_hold() -> None:
    beat = returns_from_values(3000.0, 3300.0, 3100.0)
    assert beat["edge_pct"] > 0
    lose = returns_from_values(3000.0, 2900.0, 3100.0)
    assert lose["edge_pct"] < 0


def test_fees_reduce_buy_hold_value() -> None:
    symbols = ["MSFT", "AAPL", "SMH"]
    start = {s: 100.0 for s in symbols}
    end = {s: 110.0 for s in symbols}
    gross = equal_weight_bh_value(3000.0, symbols, start, end, subtract_initial_buy_fees=False)
    net = equal_weight_bh_value(3000.0, symbols, start, end, subtract_initial_buy_fees=True)
    assert gross == 3300.0
    assert net < gross
