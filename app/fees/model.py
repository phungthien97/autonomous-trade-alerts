"""IBKR Pro US-equity fee estimates from published schedules (R2, 2026-10).

Rates are public IBKR Pro figures for US stocks/ETFs — not live scrapes.
Refresh from https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
and Activity/Flex when paper/live fills exist (G6). Exchange venue fees/rebates
are omitted (highly path-dependent); Tiered may add them in practice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["BUY", "SELL"]
FxMode = Literal["auto", "manual"]
CommissionPlan = Literal["tiered", "fixed"]

# Sources checked 2026-10-07 (IBKR Pro, United States stocks/ETFs).
_SOURCE_DATE = "2026-10-07"


@dataclass(frozen=True)
class FeeSchedule:
    plan: CommissionPlan
    commission_min_usd: float
    commission_per_share: float
    commission_max_pct: float  # fraction of trade value (IBKR: 0.01 = 1%)
    sec_rate: float
    taf_per_share: float
    cat_per_share: float
    clearing_per_share: float
    pass_through_fraction: float  # NYSE + FINRA pass-throughs on commission
    slippage_bps: float
    # Manual IDEALPRO FX (Tier I): 0.20 bp of notional, min USD 2
    fx_manual_min_usd: float
    fx_manual_bps: float
    # Auto currency conversion: ~0.03% rate adjustment, no separate commission
    fx_auto_bps: float


def ibkr_pro_tiered_us_stock_schedule() -> FeeSchedule:
    """IBKR Pro Tiered — recommended for small accounts (lower order minimum)."""
    return FeeSchedule(
        plan="tiered",
        commission_min_usd=0.35,
        commission_per_share=0.0035,
        commission_max_pct=0.01,
        sec_rate=0.0000206,
        # Normal FINRA TAF; IBKR showed USD 0.00 during Oct–Dec 2026 holiday.
        taf_per_share=0.000195,
        cat_per_share=0.000003,
        clearing_per_share=0.00020,
        # NYSE 0.000175 + FINRA 0.00056 of commission
        pass_through_fraction=0.000735,
        slippage_bps=5.0,
        fx_manual_min_usd=2.0,
        fx_manual_bps=0.20,
        fx_auto_bps=3.0,  # 0.03%
    )


def ibkr_pro_fixed_us_stock_schedule() -> FeeSchedule:
    """IBKR Pro Fixed — higher min; fewer venue pass-throughs (regs still apply)."""
    return FeeSchedule(
        plan="fixed",
        commission_min_usd=1.00,
        commission_per_share=0.005,
        commission_max_pct=0.01,
        sec_rate=0.0000206,
        taf_per_share=0.000195,
        cat_per_share=0.000003,
        # Fixed plan: clearing/exchange typically bundled; keep regs + slip.
        clearing_per_share=0.0,
        pass_through_fraction=0.0,
        slippage_bps=5.0,
        fx_manual_min_usd=2.0,
        fx_manual_bps=0.20,
        fx_auto_bps=3.0,
    )


def default_ibkr_us_stock_schedule() -> FeeSchedule:
    """Default live fee schedule: IBKR Pro Tiered (R2 choice for ~$1k accounts)."""
    return ibkr_pro_tiered_us_stock_schedule()


def estimate_equity_order_fees(
    side: Side,
    quantity: float,
    price: float,
    schedule: FeeSchedule,
) -> dict[str, float]:
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if quantity < 0 or price < 0:
        raise ValueError("quantity and price must be non-negative")

    notional = float(quantity) * float(price)
    if quantity <= 0:
        commission = 0.0
    else:
        raw_commission = float(quantity) * schedule.commission_per_share
        commission = max(schedule.commission_min_usd, raw_commission)
        if schedule.commission_max_pct > 0 and notional > 0:
            commission = min(commission, notional * schedule.commission_max_pct)

    sec = notional * schedule.sec_rate if side == "SELL" else 0.0
    finra_taf = float(quantity) * schedule.taf_per_share if side == "SELL" else 0.0
    cat = float(quantity) * schedule.cat_per_share
    clearing = float(quantity) * schedule.clearing_per_share
    pass_through = commission * schedule.pass_through_fraction
    slippage = notional * (schedule.slippage_bps / 10_000.0)
    components = {
        "commission": commission,
        "sec": sec,
        "finra_taf": finra_taf,
        "cat": cat,
        "clearing": clearing,
        "pass_through": pass_through,
        "slippage": slippage,
    }
    components["total"] = sum(components.values())
    return components


def estimate_round_trip_fees(
    quantity: float,
    buy_price: float,
    sell_price: float,
    schedule: FeeSchedule,
) -> float:
    buy = estimate_equity_order_fees("BUY", quantity, buy_price, schedule)
    sell = estimate_equity_order_fees("SELL", quantity, sell_price, schedule)
    return buy["total"] + sell["total"]


def estimate_fx_conversion_fee(
    notional_usd: float,
    schedule: FeeSchedule,
    mode: FxMode = "auto",
) -> float:
    """FX cost for CAD↔USD funding/conversion.

    Prefer ``auto`` below ~USD 6,667 (0.03% vs manual USD 2 min).
    """
    if notional_usd < 0:
        raise ValueError("notional_usd must be non-negative")
    if notional_usd == 0:
        return 0.0
    if mode == "auto":
        return float(notional_usd) * (schedule.fx_auto_bps / 10_000.0)
    if mode == "manual":
        raw = float(notional_usd) * (schedule.fx_manual_bps / 10_000.0)
        return max(schedule.fx_manual_min_usd, raw)
    raise ValueError(f"mode must be 'auto' or 'manual', got {mode!r}")


def estimate_lambda_per_trip(
    quantity: float,
    price: float,
    schedule: FeeSchedule | None = None,
    *,
    include_funding_fx: bool = False,
    funding_fx_notional_usd: float | None = None,
    fx_mode: FxMode = "auto",
) -> float:
    """Recommended ``lambda_per_trip`` (USD) from modeled round-trip cost.

    Uses the same buy/sell price (friction-only). Optionally amortizes one
    funding FX conversion into the trip estimate when ``include_funding_fx``.
    """
    sched = schedule or default_ibkr_us_stock_schedule()
    rt = estimate_round_trip_fees(quantity, price, price, sched)
    if include_funding_fx:
        fx_n = float(funding_fx_notional_usd if funding_fx_notional_usd is not None else quantity * price)
        rt += estimate_fx_conversion_fee(fx_n, sched, mode=fx_mode)
    return rt


def compare_commission_plans(
    quantity: float,
    price: float,
) -> dict[str, float | str]:
    """Side-by-side Tiered vs Fixed round-trip totals (same qty/price)."""
    tiered = ibkr_pro_tiered_us_stock_schedule()
    fixed = ibkr_pro_fixed_us_stock_schedule()
    t_rt = estimate_round_trip_fees(quantity, price, price, tiered)
    f_rt = estimate_round_trip_fees(quantity, price, price, fixed)
    winner: CommissionPlan = "tiered" if t_rt <= f_rt else "fixed"
    return {
        "quantity": float(quantity),
        "price": float(price),
        "tiered_round_trip_usd": t_rt,
        "fixed_round_trip_usd": f_rt,
        "cheaper_plan": winner,
        "source_date": _SOURCE_DATE,
    }
