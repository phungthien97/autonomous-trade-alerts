"""Fee model: IBKR Pro US equity schedules (R2)."""

from __future__ import annotations

from app.fees import (
    compare_commission_plans,
    default_ibkr_us_stock_schedule,
    estimate_equity_order_fees,
    estimate_fx_conversion_fee,
    estimate_lambda_per_trip,
    estimate_round_trip_fees,
    ibkr_pro_fixed_us_stock_schedule,
    ibkr_pro_tiered_us_stock_schedule,
)


def test_default_is_tiered() -> None:
    schedule = default_ibkr_us_stock_schedule()
    assert schedule.plan == "tiered"
    assert schedule.commission_min_usd == 0.35
    assert schedule.commission_per_share == 0.0035


def test_buy_hits_commission_minimum() -> None:
    schedule = default_ibkr_us_stock_schedule()
    breakdown = estimate_equity_order_fees("BUY", quantity=1.0, price=100.0, schedule=schedule)
    raw = 1.0 * schedule.commission_per_share
    assert raw < schedule.commission_min_usd
    assert breakdown["commission"] == schedule.commission_min_usd
    assert breakdown["sec"] == 0.0
    assert breakdown["finra_taf"] == 0.0
    assert breakdown["total"] >= schedule.commission_min_usd


def test_sell_includes_sec_and_taf() -> None:
    schedule = default_ibkr_us_stock_schedule()
    qty, price = 100.0, 50.0
    breakdown = estimate_equity_order_fees("SELL", quantity=qty, price=price, schedule=schedule)
    notional = qty * price
    assert breakdown["sec"] == notional * schedule.sec_rate
    assert breakdown["finra_taf"] == qty * schedule.taf_per_share
    assert breakdown["sec"] > 0.0
    assert breakdown["finra_taf"] > 0.0


def test_commission_capped_at_one_percent() -> None:
    """IBKR max 1% of trade value (e.g. cheap stock Fixed example)."""
    schedule = ibkr_pro_fixed_us_stock_schedule()
    qty, price = 1000.0, 0.25
    notional = qty * price  # 250
    breakdown = estimate_equity_order_fees("BUY", qty, price, schedule)
    uncapped = max(schedule.commission_min_usd, qty * schedule.commission_per_share)
    assert uncapped > notional * schedule.commission_max_pct
    assert breakdown["commission"] == notional * schedule.commission_max_pct


def test_round_trip_totals_buy_plus_sell() -> None:
    schedule = default_ibkr_us_stock_schedule()
    qty, buy_px, sell_px = 10.0, 100.0, 110.0
    buy = estimate_equity_order_fees("BUY", qty, buy_px, schedule)
    sell = estimate_equity_order_fees("SELL", qty, sell_px, schedule)
    total = estimate_round_trip_fees(qty, buy_px, sell_px, schedule)
    assert total == buy["total"] + sell["total"]


def test_fx_auto_cheaper_than_manual_on_small_conversion() -> None:
    schedule = default_ibkr_us_stock_schedule()
    notional = 1000.0
    auto = estimate_fx_conversion_fee(notional, schedule, mode="auto")
    manual = estimate_fx_conversion_fee(notional, schedule, mode="manual")
    assert auto == notional * (schedule.fx_auto_bps / 10_000.0)
    assert manual == schedule.fx_manual_min_usd
    assert auto < manual


def test_fx_manual_min_applies_on_small_conversion() -> None:
    schedule = default_ibkr_us_stock_schedule()
    tiny = estimate_fx_conversion_fee(100.0, schedule, mode="manual")
    assert tiny == schedule.fx_manual_min_usd
    large = estimate_fx_conversion_fee(2_000_000.0, schedule, mode="manual")
    raw = 2_000_000.0 * (schedule.fx_manual_bps / 10_000.0)
    assert raw > schedule.fx_manual_min_usd
    assert large == raw


def test_tiered_cheaper_than_fixed_at_one_share() -> None:
    cmp = compare_commission_plans(quantity=1.0, price=335.0)
    assert cmp["cheaper_plan"] == "tiered"
    assert float(cmp["tiered_round_trip_usd"]) < float(cmp["fixed_round_trip_usd"])


def test_lambda_per_trip_matches_round_trip() -> None:
    schedule = ibkr_pro_tiered_us_stock_schedule()
    qty, price = 1.0, 200.0
    expected = estimate_round_trip_fees(qty, price, price, schedule)
    assert estimate_lambda_per_trip(qty, price, schedule) == expected
    # Small-account 1-share trades: λ roughly $1–3 under Tiered + 5 bps slip
    assert 0.5 < expected < 3.0
