"""Unit tests for money-first dashboard helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.remote.money import (
    bh_edge_proxy,
    book_nav,
    book_status_line,
    cash_and_invested,
    distance_to_buy_pct,
    distance_to_sell_pct,
    filter_book_positions,
    from_equity_csv,
    live_money_snapshot,
    position_rows,
    returns_vs_start,
)


def test_book_nav_invested_plus_cash() -> None:
    positions = [
        {"symbol": "AAPL", "shares": 2.0, "cash": 0.0, "last_price": 100.0},
        {"symbol": "MSFT", "shares": 0.0, "cash": 1000.0, "last_price": 400.0},
    ]
    assert book_nav(positions) == 1200.0
    assert cash_and_invested(positions) == (1000.0, 200.0)


def test_book_nav_falls_back_to_total_cash() -> None:
    assert book_nav([], total_cash=3000.0) == 3000.0


def test_returns_vs_start() -> None:
    metrics = returns_vs_start(1100.0, 1000.0)
    assert abs(metrics["bot_return_pct"] - 10.0) < 1e-9


def test_distance_to_sell_and_buy() -> None:
    # peak 100, sell_drop 10% → trigger 90; price 95 → ~5.26% above sell
    sell = distance_to_sell_pct(95.0, 100.0, 0.10)
    assert sell is not None and abs(sell - ((95 - 90) / 95) * 100) < 1e-6
    # trough 100, buy_rise 5% → trigger 105; price 100 → 5% below buy
    buy = distance_to_buy_pct(100.0, 100.0, 0.05)
    assert buy is not None and abs(buy - 5.0) < 1e-6


def test_position_rows_weights_and_cues() -> None:
    positions = [
        {"symbol": "AAPL", "shares": 2.0, "cash": 0.0, "last_price": 100.0, "peak": 110.0, "trough": None},
        {"symbol": "MSFT", "shares": 0.0, "cash": 800.0, "last_price": 400.0, "peak": None, "trough": 380.0},
    ]
    picker = [
        {"symbol": "AAPL", "buy_rise": 0.02, "sell_drop": 0.05, "exit_only": False, "awaiting_first_buy": False},
        {"symbol": "MSFT", "buy_rise": 0.03, "sell_drop": 0.04, "exit_only": False, "awaiting_first_buy": True},
    ]
    rows = position_rows(positions, nav=1000.0, picker_active=picker)
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["AAPL"]["value"] == 200.0
    assert by_sym["AAPL"]["weight_pct"] == 20.0
    assert by_sym["AAPL"]["to_sell_pct"] is not None
    assert by_sym["AAPL"]["flag"] == "in stock"
    assert by_sym["MSFT"]["value"] == 800.0
    assert by_sym["MSFT"]["to_buy_pct"] is not None
    assert by_sym["MSFT"]["flag"] == "awaiting buy"


def test_from_equity_csv_day_delta(tmp_path: Path) -> None:
    path = tmp_path / "equity.csv"
    path.write_text(
        "Datetime,symbol,Price,Portfolio_Value\n"
        "2026-10-16T20:00:00+00:00,AAPL,100,1000\n"
        "2026-10-16T20:00:00+00:00,MSFT,200,1000\n"
        "2026-10-17T20:00:00+00:00,AAPL,110,1100\n"
        "2026-10-17T20:00:00+00:00,MSFT,210,1050\n",
        encoding="utf-8",
    )
    summary = from_equity_csv(path)
    assert summary["nav"] == 2150.0
    assert summary["prior_nav"] == 2000.0
    assert summary["day_delta"] == 150.0
    assert abs(summary["day_delta_pct"] - 7.5) < 1e-9
    assert summary["start_prices"]["AAPL"] == 100.0
    assert summary["latest_prices"]["AAPL"] == 110.0


def test_bh_edge_proxy_ok() -> None:
    edge = bh_edge_proxy(
        starting_cash=1000.0,
        symbols=["AAPL", "MSFT"],
        start_prices={"AAPL": 100.0, "MSFT": 200.0},
        end_prices={"AAPL": 110.0, "MSFT": 220.0},
        bot_nav=1100.0,
    )
    assert edge["ok"] is True
    assert "edge_pct" in edge


def test_bh_edge_proxy_missing_prices() -> None:
    edge = bh_edge_proxy(
        starting_cash=1000.0,
        symbols=["AAPL", "MSFT"],
        start_prices={"AAPL": 100.0},
        end_prices={"AAPL": 110.0},
        bot_nav=1100.0,
    )
    assert edge["ok"] is False


def test_live_money_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "equity.csv"
    path.write_text(
        "Datetime,symbol,Price,Portfolio_Value\n"
        "2026-10-16T20:00:00+00:00,AAPL,100,1000\n"
        "2026-10-17T20:00:00+00:00,AAPL,105,1050\n",
        encoding="utf-8",
    )
    snap = live_money_snapshot(
        positions=[{"symbol": "AAPL", "shares": 10.0, "cash": 0.0, "last_price": 105.0, "peak": 110.0}],
        total_cash=1000.0,
        equity_path=path,
        symbols=["AAPL"],
        picker_active=[{"symbol": "AAPL", "buy_rise": 0.02, "sell_drop": 0.05}],
    )
    assert snap["nav"] == 1050.0
    assert abs(snap["bot_return_pct"] - 5.0) < 1e-9
    assert snap["day_delta"] == 50.0  # 10 shares × $5 mark move
    assert abs(snap["day_delta_pct"] - (50.0 / 1050.0) * 100) < 1e-9
    assert snap["holdings"][0]["to_sell_pct"] is not None


def test_live_money_snapshot_flat_day_delta_zero(tmp_path: Path) -> None:
    """All-cash book: day Δ is 0 even if equity.csv Portfolio_Value jumped (sleeve resize)."""
    path = tmp_path / "equity.csv"
    path.write_text(
        "Datetime,symbol,Price,Portfolio_Value\n"
        "2026-10-16T20:00:00+00:00,AAPL,100,333\n"
        "2026-10-17T20:00:00+00:00,AAPL,105,1000\n",
        encoding="utf-8",
    )
    snap = live_money_snapshot(
        positions=[{"symbol": "AAPL", "shares": 0.0, "cash": 1000.0, "last_price": 105.0}],
        total_cash=1000.0,
        equity_path=path,
        symbols=["AAPL"],
    )
    assert snap["nav"] == 1000.0
    assert snap["day_delta"] == 0.0
    assert snap["day_delta_pct"] == 0.0


def test_filter_book_positions_drops_orphan_cash() -> None:
    positions = [
        {"symbol": "AAPL", "shares": 0.0, "cash": 1000.0},
        {"symbol": "P", "shares": 0.0, "cash": 600.0},
        {"symbol": "OLD", "shares": 2.0, "cash": 0.0, "last_price": 10.0},
    ]
    kept = filter_book_positions(
        positions,
        symbols=["P"],
        picker_active=[{"symbol": "P", "awaiting_first_buy": True}],
    )
    syms = {r["symbol"] for r in kept}
    assert syms == {"P", "OLD"}  # OLD kept because still long


def test_live_money_snapshot_ignores_orphan_sleeves() -> None:
    snap = live_money_snapshot(
        positions=[
            {"symbol": "AAPL", "shares": 0.0, "cash": 1000.0, "last_price": 300.0},
            {"symbol": "MSFT", "shares": 0.0, "cash": 1000.0, "last_price": 500.0},
            {"symbol": "P", "shares": 0.0, "cash": 600.0, "last_price": 120.0},
            {"symbol": "FICO", "shares": 0.0, "cash": 600.0, "last_price": 800.0},
            {"symbol": "HUM", "shares": 0.0, "cash": 600.0, "last_price": 400.0},
            {"symbol": "AMGN", "shares": 0.0, "cash": 600.0, "last_price": 400.0},
            {"symbol": "VLO", "shares": 0.0, "cash": 600.0, "last_price": 400.0},
        ],
        total_cash=3000.0,
        symbols=["P", "FICO", "HUM", "AMGN", "VLO"],
        picker_active=[
            {"symbol": s, "awaiting_first_buy": True, "exit_only": False}
            for s in ["P", "FICO", "HUM", "AMGN", "VLO"]
        ],
    )
    assert snap["nav"] == 3000.0
    assert snap["cash"] == 3000.0
    assert snap["invested"] == 0.0
    assert snap["bot_return_pct"] == 0.0
    assert snap["orphan_dropped"] == 2
    assert len(snap["holdings"]) == 5
    assert "waiting SMA gate" in snap["status_line"]
    assert snap["holdings"][0]["sleeve_cash"] == 600.0
    assert snap["holdings"][0]["stock_value"] == 0.0


def test_live_money_snapshot_flat_underallocated_not_a_loss() -> None:
    """Whole-share sleeve cash can sum under book capital before leftover is parked."""
    snap = live_money_snapshot(
        positions=[
            {"symbol": "FICO", "shares": 0.0, "cash": 800.0, "last_price": 800.0},
            {"symbol": "HUM", "shares": 0.0, "cash": 428.0, "last_price": 428.0},
        ],
        total_cash=3000.0,
        symbols=["FICO", "HUM"],
        picker_active=[
            {"symbol": "FICO", "awaiting_first_buy": True},
            {"symbol": "HUM", "awaiting_first_buy": True},
        ],
    )
    assert snap["invested"] == 0.0
    assert snap["nav"] == 3000.0
    assert snap["cash"] == 3000.0
    assert snap["bot_return_pct"] == 0.0
    assert snap["edge"].get("ok") is False


def test_book_status_line_flat() -> None:
    line = book_status_line(
        [{"symbol": "P", "shares": 0.0}],
        picker_active=[{"symbol": "P", "awaiting_first_buy": True}],
    )
    assert "flat" in line and "SMA" in line


def test_account_mode_ignores_stale_long_sleeve_cash() -> None:
    snap = live_money_snapshot(
        positions=[
            {"symbol": "AMGN", "shares": 500.0, "cash": 220000.0, "last_price": 440.0, "peak": 450.0},
            {"symbol": "P", "shares": 0.0, "cash": 250000.0, "last_price": 120.0, "trough": 118.0},
        ],
        total_cash=1_000_000.0,
        symbols=["AMGN", "P"],
        picker_active=[
            {"symbol": "AMGN", "buy_rise": 0.01, "sell_drop": 0.02, "awaiting_first_buy": False},
            {"symbol": "P", "buy_rise": 0.01, "sell_drop": 0.05, "awaiting_first_buy": True},
        ],
        use_account_cash=True,
        broker_cash=400_000.0,
        broker_equity=1_000_000.0,
        broker_stock_value=600_000.0,
        available_funds=750_000.0,
        cycle_reasons={"P": "Waiting: need $119.18 (+1% from low $118.00); now $120.00"},
        orders_today_by_symbol={"AMGN": 3, "P": 1},
    )
    # Hero "In stocks" uses broker GrossPositionValue (same currency as NAV).
    assert snap["invested"] == 600_000.0
    assert snap["cash"] == 400_000.0
    assert snap["nav"] == 1_000_000.0
    # Long + AF > cash → Can deploy / buy budget capped at cash (never-borrow)
    assert snap["available_funds"] == 400_000.0
    by_sym = {r["symbol"]: r for r in snap["holdings"]}
    assert by_sym["AMGN"]["sleeve_cash"] == 0.0
    assert by_sym["AMGN"]["stock_value"] == 220_000.0  # row still USD marks
    assert by_sym["AMGN"]["flag"] == "in stock"
    assert by_sym["AMGN"]["peak"] == 450.0
    assert by_sym["AMGN"]["sell_trigger"] == 441.0  # 450 * (1 - 0.02)
    assert by_sym["AMGN"]["orders_today"] == 3
    assert by_sym["P"]["buy_budget"] == 400_000.0
    assert by_sym["P"]["planned_shares"] == 3333  # floor(400000 / 120)
    assert by_sym["P"]["trough"] == 118.0
    assert by_sym["P"]["buy_trigger"] == 119.18
    assert by_sym["P"]["reason"].startswith("Waiting:")
    assert by_sym["P"]["flag"] == "awaiting buy"
    assert by_sym["P"]["orders_today"] == 1


def test_account_mode_day_pnl_from_account_nav(tmp_path: Path) -> None:
    nav_path = tmp_path / "account_nav.csv"
    nav_path.write_text(
        "date,equity,at_utc\n"
        "2026-10-25,969898.20,2026-10-26T03:57:46+00:00\n"
        "2026-10-26,977508.62,2026-10-27T00:16:20+00:00\n",
        encoding="utf-8",
    )
    # Freeze "now" on Eastern 2026-10-26 evening so prior close is 2026-10-25.
    snap = live_money_snapshot(
        positions=[{"symbol": "P", "shares": 100.0, "cash": 0.0, "last_price": 130.0}],
        total_cash=977_508.62,
        account_nav_path=nav_path,
        symbols=["P"],
        use_account_cash=True,
        broker_cash=300_000.0,
        broker_equity=977_508.62,
        broker_stock_value=677_508.62,
        now=datetime(2026, 10, 27, 0, 20, tzinfo=timezone.utc),  # still Oct 26 ET
    )
    # Live equity vs prior Eastern day (2026-10-25), not same-day mark noise.
    assert snap["day_delta"] == pytest.approx(977_508.62 - 969_898.20)
    assert snap["day_delta_pct"] == pytest.approx(
        ((977_508.62 - 969_898.20) / 969_898.20) * 100.0
    )


def test_account_mode_flat_accrued_interest_is_not_stocks() -> None:
    """NetLiquidation − TotalCashValue includes AccruedCash — not share value."""
    snap = live_money_snapshot(
        positions=[
            {"symbol": "AMGN", "shares": 0.0, "cash": 100_000.0, "last_price": 440.0},
            {"symbol": "P", "shares": 0.0, "cash": 100_000.0, "last_price": 120.0},
        ],
        total_cash=969_903.66,
        symbols=["AMGN", "P"],
        use_account_cash=True,
        broker_cash=969_110.33,
        broker_equity=969_903.66,
        broker_stock_value=0.0,
        broker_accrued_cash=793.33,
        available_funds=969_131.41,
    )
    assert snap["invested"] == 0.0
    assert snap["cash"] == 969_110.33
    assert snap["nav"] == 969_903.66
    assert snap["accrued_cash"] == 793.33


def test_account_mode_subtracts_accrued_when_gross_missing() -> None:
    snap = live_money_snapshot(
        positions=[],
        total_cash=1_000_793.33,
        symbols=[],
        use_account_cash=True,
        broker_cash=1_000_000.0,
        broker_equity=1_000_793.33,
        broker_accrued_cash=793.33,
    )
    assert snap["invested"] == 0.0
    assert snap["accrued_cash"] == 793.33
