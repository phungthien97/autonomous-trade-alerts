from app.fees.model import FeeSchedule, default_ibkr_us_stock_schedule
from app.picker.score import score_symbol_series


def _zero_fee_schedule() -> FeeSchedule:
    base = default_ibkr_us_stock_schedule()
    return FeeSchedule(
        plan=base.plan,
        commission_min_usd=0.0,
        commission_per_share=0.0,
        commission_max_pct=0.0,
        sec_rate=0.0,
        taf_per_share=0.0,
        cat_per_share=0.0,
        clearing_per_share=0.0,
        pass_through_fraction=0.0,
        slippage_bps=0.0,
        fx_manual_min_usd=base.fx_manual_min_usd,
        fx_manual_bps=base.fx_manual_bps,
        fx_auto_bps=base.fx_auto_bps,
    )


def test_buy_and_hold_baseline_and_positive_edge_after_dip() -> None:
    # Crash then bounce: strategy stays cash into the trough, buys rebound, holds.
    closes = [100.0, 80.0, 81.6, 120.0]
    result = score_symbol_series(
        closes, buy_rise=0.02, sell_drop=0.50, initial_cash=1000.0, schedule=_zero_fee_schedule()
    )
    # B&H: 1000/100 * 120 = 1200 → +20%
    assert abs(result.bh_final_value - 1200.0) < 1e-6
    assert abs(result.bh_return - 0.20) < 1e-9
    assert result.round_trips == 0
    # Buy at 81.6 after trough 80 → ~1000/81.6*120 ≈ 1470 > B&H
    assert result.strategy_final_value > result.bh_final_value
    assert result.edge > 0


def test_fees_reduce_strategy_value_vs_zero_fee() -> None:
    # Force a round trip: buy bounce then sell drop.
    closes = [100.0, 99.0, 101.0, 110.0, 100.0, 90.0]
    zero = score_symbol_series(
        closes, buy_rise=0.01, sell_drop=0.05, initial_cash=1000.0, schedule=_zero_fee_schedule()
    )
    taxed = score_symbol_series(
        closes,
        buy_rise=0.01,
        sell_drop=0.05,
        initial_cash=1000.0,
        schedule=default_ibkr_us_stock_schedule(),
    )
    assert zero.round_trips >= 1
    assert taxed.round_trips >= 1
    assert taxed.strategy_final_value < zero.strategy_final_value


def test_whipsaw_negative_edge_after_fees() -> None:
    # Many small ripples → fees + churn lose to B&H flat-ish path.
    closes = [100.0]
    px = 100.0
    for _ in range(40):
        px *= 0.97
        closes.append(px)
        px *= 1.04
        closes.append(px)
    result = score_symbol_series(
        closes,
        buy_rise=0.02,
        sell_drop=0.02,
        initial_cash=1000.0,
        schedule=default_ibkr_us_stock_schedule(),
    )
    assert result.round_trips >= 1
    assert result.edge < 0
