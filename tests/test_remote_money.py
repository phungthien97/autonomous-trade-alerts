"""Unit tests for money-first dashboard helpers."""

from __future__ import annotations

from pathlib import Path

from app.remote.money import (
    bh_edge_proxy,
    book_nav,
    cash_and_invested,
    distance_to_buy_pct,
    distance_to_sell_pct,
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
    assert by_sym["AAPL"]["flag"] == "active"
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
