"""Trading budget: unused pool, clamp, reduce plan, control set-only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.live.budget import (
    effective_buy_pool,
    flat_buy_pool_usd,
    invested_usd,
    plan_rebalance_to_equal,
    plan_reduce_to_budget,
    reserve_underweight_longs_usd,
    unused_budget,
    withdrawable_cash_usd,
)
from app.live.control import set_trading_budget_usd
from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.paths import LivePaths


def test_unused_and_effective_pool() -> None:
    assert unused_budget(150.0, 100.0) == pytest.approx(50.0)
    assert effective_buy_pool(150.0, invested_usd=100.0, spendable_usd=500.0) == pytest.approx(50.0)
    assert effective_buy_pool(200.0, invested_usd=0.0, spendable_usd=80.0) == pytest.approx(80.0)
    assert effective_buy_pool(200.0, invested_usd=0.0, spendable_usd=0.0) == 0.0
    assert effective_buy_pool(None, invested_usd=100.0, spendable_usd=500.0) == pytest.approx(500.0)


def test_flat_buy_pool_reserves_underweight_long() -> None:
    # 500k budget / 5 = 100k target. P at 70k → reserve 30k; unused 330k → flats 300k.
    symbols = ["P", "FICO", "HUM", "AMGN", "VLO"]
    positions = {"P": 700.0, "AMGN": 200.0, "FICO": 0.0, "HUM": 0.0, "VLO": 0.0}
    prices = {"P": 100.0, "AMGN": 500.0, "FICO": 700.0, "HUM": 400.0, "VLO": 380.0}
    # invested = 70k + 100k = 170k; unused = 330k
    invested = 170_000.0
    reserved = reserve_underweight_longs_usd(
        500_000.0, symbols=symbols, positions=positions, prices=prices
    )
    assert reserved == pytest.approx(30_000.0)
    pool = flat_buy_pool_usd(
        500_000.0,
        symbols=symbols,
        positions=positions,
        prices=prices,
        invested_usd=invested,
        spendable_usd=1_000_000.0,
    )
    assert pool == pytest.approx(300_000.0)
    assert pool / 3 == pytest.approx(100_000.0)


def test_invested_usd_sums_longs() -> None:
    assert invested_usd({"A": 10.0, "B": 0.0}, {"A": 5.0, "B": 9.0}) == pytest.approx(50.0)


def test_withdrawable_cash() -> None:
    # Budget 110, invested 100 → reserve 10 of cash; cash 50 → withdrawable 40.
    assert withdrawable_cash_usd(cash_usd=50.0, budget_usd=110.0, invested_usd=100.0) == pytest.approx(
        40.0
    )


def test_reduce_plan_pro_rata() -> None:
    positions = {"A": 100.0, "B": 50.0}
    prices = {"A": 1.0, "B": 1.0}  # invested 150
    sells = plan_reduce_to_budget(positions, prices, budget_usd=110.0)
    sold = sum(s.notional for s in sells)
    assert sold == pytest.approx(40.0, abs=1.0)
    assert all(s.shares >= 1 for s in sells)


def test_reduce_budget_zero_sells_all() -> None:
    positions = {"A": 10.0, "B": 2.0}
    prices = {"A": 50.0, "B": 100.0}
    sells = plan_reduce_to_budget(positions, prices, budget_usd=0.0)
    assert {s.symbol for s in sells} == {"A", "B"}
    assert sum(s.shares for s in sells) == pytest.approx(12.0)


def test_rebalance_equal_targets_sell_and_buy() -> None:
    # budget 300 / 3 = 100 each; A=150 → sell 50; B=0 → buy 100; C=100 → flat
    positions = {"A": 150.0, "B": 0.0, "C": 100.0}
    prices = {"A": 1.0, "B": 1.0, "C": 1.0}
    plan = plan_rebalance_to_equal(
        ["A", "B", "C"],
        positions,
        prices,
        budget_usd=300.0,
        spendable_usd=200.0,
        sma20_ok={"A": True, "B": True, "C": True},
    )
    assert plan.target_per_sleeve == pytest.approx(100.0)
    assert {o.symbol: o.shares for o in plan.sells} == {"A": 50.0}
    assert {o.symbol: o.shares for o in plan.buys} == {"B": 100.0}


def test_rebalance_sma20_blocks_buy() -> None:
    positions = {"A": 0.0, "B": 0.0}
    prices = {"A": 10.0, "B": 10.0}
    plan = plan_rebalance_to_equal(
        ["A", "B"],
        positions,
        prices,
        budget_usd=200.0,
        spendable_usd=500.0,
        sma20_ok={"A": True, "B": False},
    )
    assert [o.symbol for o in plan.buys] == ["A"]
    assert any(s.symbol == "B" and s.reason == "sma20_gate" for s in plan.skipped)


def test_rebalance_cash_clamp() -> None:
    positions = {"A": 0.0, "B": 0.0}
    prices = {"A": 1.0, "B": 1.0}
    plan = plan_rebalance_to_equal(
        ["A", "B"],
        positions,
        prices,
        budget_usd=200.0,
        spendable_usd=50.0,  # can only fund 50 total buys
        sma20_ok={"A": True, "B": True},
    )
    assert sum(o.notional for o in plan.buys) == pytest.approx(50.0)


def test_rebalance_budget_zero_sells_all() -> None:
    positions = {"A": 10.0, "B": 2.0}
    prices = {"A": 5.0, "B": 5.0}
    plan = plan_rebalance_to_equal(
        ["A", "B"],
        positions,
        prices,
        budget_usd=0.0,
        spendable_usd=100.0,
        sma20_ok={"A": True, "B": True},
    )
    assert not plan.buys
    assert {o.symbol: o.shares for o in plan.sells} == {"A": 10.0, "B": 2.0}


def test_rebalance_missing_price_skipped() -> None:
    plan = plan_rebalance_to_equal(
        ["A", "B"],
        {"A": 1.0},
        {"A": 10.0},
        budget_usd=100.0,
        spendable_usd=100.0,
        sma20_ok={"A": True, "B": True},
    )
    assert any(s.symbol == "B" and s.reason == "missing_price" for s in plan.skipped)


def test_set_trading_budget_does_not_require_broker(tmp_path: Path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    cfg = LiveConfig(
        symbols=["P"],
        total_cash=1000.0,
        trading_budget_usd=500.0,
        assets=[SymbolParams(symbol="P")],
    )
    save_live_config(paths.config_path, cfg)
    paths.state_path.write_text(json.dumps({"assets": {}}), encoding="utf-8")
    written = set_trading_budget_usd(paths, 750.0)
    assert written == 750.0
    raw = json.loads(paths.config_path.read_text(encoding="utf-8"))
    assert raw["trading_budget_usd"] == 750.0
    state = json.loads(paths.state_path.read_text(encoding="utf-8"))
    assert state["trading_budget_usd"] == 750.0
