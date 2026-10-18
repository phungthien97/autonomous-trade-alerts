import numpy as np

from app.picker.rank_symbol import rank_one_symbol


def _dip_then_rally(n: int = 40, start: float = 100.0) -> list[float]:
    """Synthetic path: grind down then rally (peak/trough-friendly)."""
    px = start
    out = [px]
    for i in range(n - 1):
        if i < n // 2:
            px *= 0.98
        else:
            px *= 1.02
        out.append(px)
    return out


def test_rank_one_symbol_scores_positive_edge_on_friendly_series() -> None:
    opt = _dip_then_rally(30)
    # Score month: deeper dip then stronger recovery → cash-in-dip helps vs B&H
    score = [100.0]
    px = 100.0
    for _ in range(20):
        px *= 0.97
        score.append(px)
    for _ in range(20):
        px *= 1.03
        score.append(px)

    result = rank_one_symbol(opt, score, initial_cash=1000.0)
    assert result.skipped is False
    assert result.buy_rise is not None and result.sell_drop is not None
    assert result.edge is not None
    assert result.edge > 0


def test_rank_one_symbol_skips_short_series() -> None:
    assert rank_one_symbol([100.0], [100.0, 101.0]).skipped is True
    assert rank_one_symbol([100.0, 101.0], [100.0]).reason == "score_window_too_short"


def test_rank_one_symbol_as_dict_keys() -> None:
    result = rank_one_symbol(np.linspace(100, 90, 20), np.linspace(90, 110, 30))
    payload = result.as_dict()
    assert "edge" in payload and "buy_rise" in payload and "skipped" in payload
