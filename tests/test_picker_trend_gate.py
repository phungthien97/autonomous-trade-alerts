from app.picker.trend_gate import allow_first_buy, sma


def test_sma_and_allow_first_buy() -> None:
    flat = [10.0] * 20
    assert sma(flat, 20) == 10.0
    assert allow_first_buy(flat + [11.0]) is True
    assert allow_first_buy(flat[:-1] + [9.0], price=9.0) is False


def test_allow_first_buy_fail_closed_short_series() -> None:
    assert allow_first_buy([1.0] * 19) is False
    assert sma([1.0] * 19, 20) is None
