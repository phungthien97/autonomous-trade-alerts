"""Money-first snapshot helpers for the remote dashboard."""

from __future__ import annotations

import csv
from datetime import datetime
from math import floor
from pathlib import Path
from typing import Any

from app.live.account_nav import day_pnl_vs_prior_close
from app.live.metrics import equal_weight_bh_value, returns_from_values


def filter_book_positions(
    positions: list[dict[str, Any]],
    *,
    symbols: list[str] | None = None,
    picker_active: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Keep active-book sleeves; drop orphan cash rows from prior universes.

    Keep if: in config symbols, in picker active (incl. exit_only), or still long.
    """
    keep: set[str] = {str(s) for s in (symbols or []) if s}
    for row in picker_active or []:
        sym = row.get("symbol")
        if sym:
            keep.add(str(sym))
    out: list[dict[str, Any]] = []
    for row in positions or []:
        sym = str(row.get("symbol") or "")
        shares = float(row.get("shares") or 0.0)
        if sym in keep or shares > 0:
            out.append(row)
    return out


def book_nav(positions: list[dict[str, Any]], total_cash: float | None = None) -> float:
    """Mark-to-market book: invested + sleeve cash. Fall back to total_cash when empty."""
    invested = 0.0
    cash = 0.0
    for row in positions or []:
        shares = float(row.get("shares") or 0.0)
        px = row.get("last_price")
        if px is None:
            px = row.get("price")
        if shares and isinstance(px, (int, float)):
            invested += shares * float(px)
        cash += float(row.get("cash") or 0.0)
    nav = invested + cash
    if nav <= 0 and total_cash is not None:
        return float(total_cash)
    return nav


def cash_and_invested(positions: list[dict[str, Any]]) -> tuple[float, float]:
    cash = 0.0
    invested = 0.0
    for row in positions or []:
        shares = float(row.get("shares") or 0.0)
        px = row.get("last_price")
        if px is None:
            px = row.get("price")
        cash += float(row.get("cash") or 0.0)
        if shares and isinstance(px, (int, float)):
            invested += shares * float(px)
    return cash, invested


def book_status_line(
    positions: list[dict[str, Any]],
    *,
    picker_active: list[dict[str, Any]] | None = None,
) -> str:
    """Short human status: sleeve count + flat/invested + gate hint."""
    n = len(positions or [])
    invested = sum(
        1 for row in (positions or []) if float(row.get("shares") or 0.0) > 0
    )
    awaiting = sum(
        1
        for row in (picker_active or [])
        if row.get("awaiting_first_buy") and not row.get("exit_only")
    )
    exit_only = sum(1 for row in (picker_active or []) if row.get("exit_only"))
    if n == 0:
        return "No active sleeves"
    if invested == 0:
        bits = [f"Active: {n} sleeves", "flat"]
        if awaiting:
            bits.append("waiting SMA gate" if awaiting == n else f"{awaiting} waiting SMA gate")
        return " · ".join(bits)
    bits = [f"Active: {n} sleeves", f"{invested} in stock", f"{n - invested} in cash"]
    if exit_only:
        bits.append(f"{exit_only} exit-only")
    return " · ".join(bits)


def _parse_dt(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def from_equity_csv(path: Path) -> dict[str, Any]:
    """Summarize ``equity.csv`` (Datetime, symbol, Price, Portfolio_Value).

    Returns latest per-symbol portfolio values and prices, plus optional day delta
    when a prior same-calendar-day or previous timestamp snapshot exists.
    """
    path = Path(path)
    if not path.is_file():
        return {
            "latest_values": {},
            "latest_prices": {},
            "start_prices": {},
            "nav": None,
            "prior_nav": None,
            "day_delta": None,
            "day_delta_pct": None,
        }

    # Chronological rows
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            sym = raw.get("symbol")
            if not sym:
                continue
            try:
                value = float(raw["Portfolio_Value"])
                price = float(raw["Price"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                {
                    "symbol": str(sym),
                    "value": value,
                    "price": price,
                    "dt": _parse_dt(str(raw.get("Datetime") or "")),
                    "raw_dt": raw.get("Datetime"),
                }
            )

    latest_values: dict[str, float] = {}
    latest_prices: dict[str, float] = {}
    start_prices: dict[str, float] = {}
    for row in rows:
        sym = row["symbol"]
        if sym not in start_prices:
            start_prices[sym] = row["price"]
        latest_values[sym] = row["value"]
        latest_prices[sym] = row["price"]

    nav = sum(latest_values.values()) if latest_values else None

    # Build timestamp → symbol values map for day delta
    by_ts: dict[str, dict[str, float]] = {}
    ts_order: list[str] = []
    for row in rows:
        key = str(row["raw_dt"] or "")
        if key not in by_ts:
            by_ts[key] = {}
            ts_order.append(key)
        by_ts[key][row["symbol"]] = row["value"]

    prior_nav = None
    day_delta = None
    day_delta_pct = None
    if len(ts_order) >= 2 and nav is not None:
        last_key = ts_order[-1]
        last_dt = _parse_dt(last_key)
        prior_key = None
        # Prefer last snapshot from a previous calendar day; else previous timestamp.
        if last_dt is not None:
            last_day = last_dt.date()
            for key in reversed(ts_order[:-1]):
                dt = _parse_dt(key)
                if dt is not None and dt.date() < last_day:
                    prior_key = key
                    break
        if prior_key is None:
            prior_key = ts_order[-2]
        prior_vals = by_ts.get(prior_key) or {}
        # Align on symbols present in latest
        prior_nav = sum(prior_vals.get(sym, latest_values.get(sym, 0.0)) for sym in latest_values)
        day_delta = nav - prior_nav
        if prior_nav:
            day_delta_pct = (day_delta / prior_nav) * 100.0

    return {
        "latest_values": latest_values,
        "latest_prices": latest_prices,
        "start_prices": start_prices,
        "nav": nav,
        "prior_nav": prior_nav,
        "day_delta": day_delta,
        "day_delta_pct": day_delta_pct,
    }


def returns_vs_start(nav: float, starting_cash: float) -> dict[str, float]:
    """Bot return since start; B&H left equal so edge is 0 until bh_edge_proxy fills it."""
    return returns_from_values(starting_cash, nav, nav)


def bh_edge_proxy(
    *,
    starting_cash: float,
    symbols: list[str],
    start_prices: dict[str, float],
    end_prices: dict[str, float],
    bot_nav: float,
) -> dict[str, Any]:
    """Bot vs equal-weight B&H when start/end prices cover the universe."""
    if starting_cash <= 0 or not symbols:
        return {"ok": False, "reason": "missing start cash or symbols"}
    missing = [s for s in symbols if s not in start_prices or s not in end_prices]
    if missing:
        return {"ok": False, "reason": "B&H when prices available", "missing": missing}
    try:
        bh_end = equal_weight_bh_value(starting_cash, symbols, start_prices, end_prices)
        metrics = returns_from_values(starting_cash, bot_nav, bh_end)
    except (ValueError, KeyError) as exc:
        return {"ok": False, "reason": str(exc)}
    return {
        "ok": True,
        "bot_return_pct": metrics["bot_return_pct"],
        "bh_return_pct": metrics["bh_return_pct"],
        "edge_pct": metrics["edge_pct"],
        "bh_end": bh_end,
    }


def distance_to_sell_pct(price: float, peak: float, sell_drop: float) -> float | None:
    """Percent above the sell trigger (peak × (1 − sell_drop)). Negative = at/through."""
    if price <= 0 or peak <= 0 or sell_drop is None:
        return None
    trigger = float(peak) * (1.0 - float(sell_drop))
    if trigger <= 0:
        return None
    return ((float(price) - trigger) / float(price)) * 100.0


def distance_to_buy_pct(price: float, trough: float, buy_rise: float) -> float | None:
    """Percent below the buy trigger (trough × (1 + buy_rise)). Negative = at/through."""
    if price <= 0 or trough <= 0 or buy_rise is None:
        return None
    trigger = float(trough) * (1.0 + float(buy_rise))
    if trigger <= 0:
        return None
    return ((trigger - float(price)) / float(price)) * 100.0


def _picker_flag_label(flag: dict[str, Any] | None) -> str:
    if not flag:
        return ""
    if flag.get("exit_only"):
        return "exit only"
    if flag.get("awaiting_first_buy"):
        return "awaiting buy"
    return "active"


def position_rows(
    positions: list[dict[str, Any]],
    *,
    nav: float | None = None,
    picker_active: list[dict[str, Any]] | None = None,
    use_account_cash: bool = False,
    available_cash: float | None = None,
    cycle_reasons: dict[str, str] | None = None,
    orders_today_by_symbol: dict[str, int] | None = None,
    trading_budget_usd: float | None = None,
    sma20_by_symbol: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Enrich positions with mkt_value, weight_pct, and buy/sell distance cues."""
    flags = {str(row.get("symbol")): row for row in (picker_active or []) if row.get("symbol")}
    reasons = {str(k): str(v) for k, v in (cycle_reasons or {}).items() if v}
    sma20_map = {
        str(k).upper(): float(v)
        for k, v in (sma20_by_symbol or {}).items()
        if v is not None
    }
    orders_by_sym = {
        str(k): int(v)
        for k, v in (orders_today_by_symbol or {}).items()
        if v is not None
    }
    total = float(nav) if nav and nav > 0 else book_nav(positions)
    flat_n = sum(1 for row in (positions or []) if float(row.get("shares") or 0.0) <= 0)
    # Equal-sleeve target for dashboard copy (budget / N non-exit_only).
    equal_target = None
    if use_account_cash and trading_budget_usd is not None and float(trading_budget_usd) > 0:
        n_eq = 0
        for prow in positions or []:
            psym = str(prow.get("symbol") or "")
            pflag = flags.get(psym) if psym else None
            if pflag and pflag.get("exit_only"):
                continue
            n_eq += 1
        if n_eq <= 0:
            n_eq = len(positions or [])
        if n_eq > 0:
            equal_target = float(trading_budget_usd) / float(n_eq)
    buy_budget = None
    if use_account_cash and available_cash is not None and flat_n > 0:
        # available_cash is already flat_buy_pool (underweight longs reserved).
        buy_budget = max(0.0, float(available_cash)) / float(flat_n)
        if equal_target is not None:
            buy_budget = min(buy_budget, float(equal_target))

    out: list[dict[str, Any]] = []
    for row in positions or []:
        sym = str(row.get("symbol") or "")
        shares = float(row.get("shares") or 0.0)
        cash = float(row.get("cash") or 0.0)
        # Whole-account mode: long sleeves do not own idle cash; ignore stale sleeve cash.
        if use_account_cash and shares > 0:
            cash = 0.0
        px = row.get("last_price")
        if px is None:
            px = row.get("price")
        price = float(px) if isinstance(px, (int, float)) else None
        mkt_value = (shares * price) if price is not None and shares else 0.0
        sleeve_value = mkt_value + cash
        weight_base = mkt_value if use_account_cash else sleeve_value
        weight = (weight_base / total * 100.0) if total > 0 and weight_base else None

        flag = flags.get(sym)
        to_sell = None
        to_buy = None
        buy_trigger = None
        sell_trigger = None
        peak = row.get("peak")
        trough = row.get("trough")
        sell_drop = flag.get("sell_drop") if flag else None
        buy_rise = flag.get("buy_rise") if flag else None
        if flag and price is not None:
            if shares > 0 and isinstance(peak, (int, float)) and sell_drop is not None:
                sell_trigger = float(peak) * (1.0 - float(sell_drop))
                to_sell = distance_to_sell_pct(price, float(peak), float(sell_drop))
            if shares <= 0 and isinstance(trough, (int, float)) and buy_rise is not None:
                buy_trigger = float(trough) * (1.0 + float(buy_rise))
                to_buy = distance_to_buy_pct(price, float(trough), float(buy_rise))

        state = "in stock" if shares > 0 else "flat"
        flag_label = _picker_flag_label(flag)
        if flag_label == "exit only":
            state = "exit only"
        elif shares <= 0 and flag_label == "awaiting buy":
            state = "awaiting buy"

        planned_shares = None
        sleeve_budget = round(buy_budget, 2) if buy_budget is not None and shares <= 0 else None
        if sleeve_budget is not None and price is not None and price > 0:
            planned_shares = int(floor(sleeve_budget / float(price)))

        out.append(
            {
                "symbol": sym,
                "shares": shares,
                "price": price,
                "cash": round(cash, 2),
                "value": round(sleeve_value if not use_account_cash else mkt_value, 2),
                "mkt_value": round(mkt_value, 2),
                "stock_value": round(mkt_value, 2),
                "sleeve_cash": round(cash, 2),
                "sleeve_total": round(sleeve_value, 2),
                "buy_budget": sleeve_budget,
                "planned_shares": planned_shares,
                "equal_target_usd": round(equal_target, 2) if equal_target is not None else None,
                "sma20": round(sma20_map[sym], 4) if sym in sma20_map else None,
                "weight_pct": round(weight, 1) if weight is not None else None,
                "to_sell_pct": round(to_sell, 1) if to_sell is not None else None,
                "to_buy_pct": round(to_buy, 1) if to_buy is not None else None,
                "buy_trigger": round(buy_trigger, 2) if buy_trigger is not None else None,
                "sell_trigger": round(sell_trigger, 2) if sell_trigger is not None else None,
                "peak": float(peak) if isinstance(peak, (int, float)) else None,
                "trough": float(trough) if isinstance(trough, (int, float)) else None,
                "flag": state,
                "reason": reasons.get(sym) or "",
                "last_action": row.get("last_action"),
                "orders_today": int(orders_by_sym.get(sym) or 0),
            }
        )
    return out


def _day_pnl_from_prices(
    positions: list[dict[str, Any]],
    *,
    latest_prices: dict[str, float],
    prior_prices: dict[str, float],
) -> tuple[float | None, float | None]:
    """Unrealized day P&L from share mark changes (ignores cash / sleeve resizes)."""
    if not positions or not prior_prices:
        return None, None
    pnl = 0.0
    any_held = False
    for row in positions:
        shares = float(row.get("shares") or 0.0)
        if shares <= 0:
            continue
        sym = str(row.get("symbol") or "")
        px_now = latest_prices.get(sym)
        px_prior = prior_prices.get(sym)
        if px_now is None or px_prior is None:
            continue
        any_held = True
        pnl += shares * (float(px_now) - float(px_prior))
    if not any_held:
        # Flat book: no market P&L today.
        return 0.0, 0.0
    return pnl, None


def _prior_day_prices_from_equity_rows(path: Path) -> dict[str, float]:
    """Last price per symbol from the most recent prior calendar day in equity.csv."""
    path = Path(path)
    if not path.is_file():
        return {}
    rows: list[tuple[datetime | None, str, float]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            sym = raw.get("symbol")
            if not sym:
                continue
            try:
                price = float(raw["Price"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append((_parse_dt(str(raw.get("Datetime") or "")), str(sym), price))
    if not rows:
        return {}
    last_dt = None
    for dt, _, _ in reversed(rows):
        if dt is not None:
            last_dt = dt
            break
    if last_dt is None:
        return {}
    last_day = last_dt.date()
    prior: dict[str, float] = {}
    prior_day = None
    for dt, sym, price in reversed(rows):
        if dt is None or dt.date() >= last_day:
            continue
        if prior_day is None:
            prior_day = dt.date()
        if dt.date() != prior_day:
            break
        if sym not in prior:
            prior[sym] = price
    return prior


def live_money_snapshot(
    *,
    positions: list[dict[str, Any]],
    total_cash: float | None,
    equity_path: Path | None = None,
    account_nav_path: Path | None = None,
    symbols: list[str] | None = None,
    picker_active: list[dict[str, Any]] | None = None,
    use_account_cash: bool = False,
    broker_cash: float | None = None,
    broker_equity: float | None = None,
    available_funds: float | None = None,
    broker_stock_value: float | None = None,
    broker_accrued_cash: float | None = None,
    account_currency: str | None = None,
    usd_cad_rate: float | None = None,
    fx_rates: dict[str, float] | None = None,
    trading_budget_usd: float | None = None,
    cycle_reasons: dict[str, str] | None = None,
    orders_today_by_symbol: dict[str, int] | None = None,
    sma20_by_symbol: dict[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble Live-tab money hero + holdings from files (and optional equity.csv)."""
    from app.live.budget import (
        effective_buy_pool,
        flat_buy_pool_usd,
        unused_budget,
        withdrawable_cash_usd,
    )

    start = float(total_cash) if total_cash is not None else None
    book_positions = filter_book_positions(
        positions,
        symbols=symbols,
        picker_active=picker_active,
    )
    spendable_for_buys: float | None = None
    spendable_for_shares: float | None = None
    accrued: float | None = (
        float(broker_accrued_cash) if broker_accrued_cash is not None else None
    )
    if use_account_cash:
        from app.account_snapshot import compute_spendable, to_usd

        # Paper IBKR base currency may be CAD. Prefer broker tags in that currency:
        # NetLiquidation, TotalCashValue, GrossPositionValue, AccruedCash.
        # Do NOT use equity − cash for "stocks" — that residual is often AccruedCash
        # (interest), not share holdings. Keep native CAD for Day P&L continuity.
        if broker_equity is not None and float(broker_equity) > 0:
            nav = float(broker_equity)
        elif start is not None and start > 0:
            nav = float(start)
        else:
            nav = 0.0
        cash = float(broker_cash) if broker_cash is not None else 0.0
        if broker_stock_value is not None:
            invested = max(0.0, float(broker_stock_value))
        elif broker_cash is not None and nav > 0 and accrued is not None:
            invested = max(0.0, nav - cash - accrued)
        elif broker_cash is not None and nav > 0:
            invested = max(0.0, nav - cash)
        else:
            invested = 0.0
            for row in book_positions:
                shares = float(row.get("shares") or 0.0)
                px = row.get("last_price")
                if px is None:
                    px = row.get("price")
                if shares > 0 and isinstance(px, (int, float)):
                    invested += shares * float(px)
            if nav <= 0:
                nav = invested + cash + (accrued or 0.0)
        # Never-borrow: while long, do not size off AvailableFunds > cash
        # (that gap is margin against open stock). Native account currency.
        if broker_cash is not None or available_funds is not None:
            gross_for_spend = (
                float(broker_stock_value)
                if broker_stock_value is not None
                else (invested if invested > 0 else None)
            )
            spendable_for_buys = compute_spendable(
                float(broker_cash) if broker_cash is not None else 0.0,
                float(available_funds) if available_funds is not None else None,
                gross_for_spend,
            )
            # Planned share counts need USD (US equity prices).
            spendable_for_shares = to_usd(
                spendable_for_buys,
                account_currency=str(account_currency or "USD"),
                usd_cad_rate=usd_cad_rate,
                fx_rates=fx_rates,
            )
    else:
        cash, invested = cash_and_invested(book_positions)
        nav = book_nav(book_positions, total_cash=start)

    equity = from_equity_csv(equity_path) if equity_path else from_equity_csv(Path("__missing__"))
    # Prefer live MTM nav; use equity.csv nav only as fallback when flat files empty
    if nav <= 0 and equity.get("nav"):
        nav = float(equity["nav"])

    bot_return_pct = None
    edge: dict[str, Any] = {"ok": False, "reason": "B&H when prices available"}
    # Flat book (no shares): no trading P&L yet — do not invent a loss from
    # under-allocated sleeve cash or from equity.csv B&H marks.
    if use_account_cash:
        # Book capital tracks live equity — "since start" would always read ~0%.
        bot_return_pct = None
        edge = {"ok": False, "reason": "since-start return paused while book tracks live equity"}
    elif invested <= 0:
        bot_return_pct = 0.0
        if start is not None and start > 0 and cash + 0.01 < start:
            # Unassigned leftover after whole-share sizing — still part of the book.
            nav = float(start)
            cash = float(start)
    elif start and start > 0 and nav > 0:
        bot_return_pct = returns_vs_start(nav, start)["bot_return_pct"]

    syms = list(symbols or [])
    if (
        not use_account_cash
        and invested > 0
        and start
        and syms
        and equity.get("start_prices")
        and equity.get("latest_prices")
    ):
        edge = bh_edge_proxy(
            starting_cash=start,
            symbols=syms,
            start_prices=equity["start_prices"],
            end_prices=equity["latest_prices"],
            bot_nav=nav,
        )
        if edge.get("ok") and bot_return_pct is None:
            bot_return_pct = edge.get("bot_return_pct")

    # Day Δ:
    # - Account mode: live NetLiquidation vs prior Eastern day in account_nav.csv
    #   (includes realized trades, cash, accrued interest — not just open marks).
    # - Book mode: share mark changes only (ignore sleeve cash resizes).
    day_delta: float | None
    day_delta_pct: float | None
    if use_account_cash:
        day_delta, day_delta_pct = None, None
        if account_nav_path is not None and nav > 0:
            day_delta, day_delta_pct = day_pnl_vs_prior_close(
                account_nav_path,
                current_equity=nav,
                now=now,
            )
    elif invested <= 0:
        day_delta, day_delta_pct = 0.0, 0.0
    else:
        prior_prices = _prior_day_prices_from_equity_rows(equity_path) if equity_path else {}
        day_delta, day_delta_pct = _day_pnl_from_prices(
            book_positions,
            latest_prices=equity.get("latest_prices") or {},
            prior_prices=prior_prices,
        )
        if day_delta is not None and nav > 0 and day_delta_pct is None:
            day_delta_pct = (day_delta / nav) * 100.0

    # USD mark of longs for budget math (US equity prices).
    invested_usd_marks = 0.0
    for row in book_positions:
        shares = float(row.get("shares") or 0.0)
        px = row.get("last_price")
        if px is None:
            px = row.get("price")
        if shares > 0 and isinstance(px, (int, float)) and float(px) > 0:
            invested_usd_marks += shares * float(px)

    buy_pool_usd = None
    unused_usd = None
    withdrawable_usd = None
    if use_account_cash and spendable_for_shares is not None:
        # Raw unused (budget - invested), for metrics.
        unused_raw = effective_buy_pool(
            trading_budget_usd,
            invested_usd=invested_usd_marks,
            spendable_usd=float(spendable_for_shares),
        )
        pos_map = {
            str(r.get("symbol") or "").upper(): float(r.get("shares") or 0.0)
            for r in book_positions
            if r.get("symbol")
        }
        px_map: dict[str, float] = {}
        for r in book_positions:
            sym = str(r.get("symbol") or "").upper()
            if not sym:
                continue
            px = r.get("last_price")
            if px is None:
                px = r.get("price")
            if isinstance(px, (int, float)) and float(px) > 0:
                px_map[sym] = float(px)
        syms = [str(r.get("symbol")).upper() for r in book_positions if r.get("symbol")]
        if picker_active:
            # Prefer non-exit_only active list order when present.
            syms = [
                str(r.get("symbol")).upper()
                for r in picker_active
                if r.get("symbol") and not r.get("exit_only")
            ] or syms
        # Flat signal buys reserve underweight long gaps (e.g. P at 70k of 100k).
        buy_pool_usd = flat_buy_pool_usd(
            trading_budget_usd,
            symbols=syms,
            positions=pos_map,
            prices=px_map,
            invested_usd=invested_usd_marks,
            spendable_usd=float(spendable_for_shares),
        ) if trading_budget_usd is not None else unused_raw
        if trading_budget_usd is not None:
            unused_usd = unused_budget(float(trading_budget_usd), invested_usd_marks)
            withdrawable_usd = withdrawable_cash_usd(
                cash_usd=float(spendable_for_shares),
                budget_usd=float(trading_budget_usd),
                invested_usd=invested_usd_marks,
            )

    holdings = position_rows(
        book_positions,
        nav=nav,
        picker_active=picker_active,
        use_account_cash=use_account_cash,
        available_cash=buy_pool_usd if use_account_cash else None,
        cycle_reasons=cycle_reasons,
        orders_today_by_symbol=orders_today_by_symbol,
        trading_budget_usd=trading_budget_usd,
        sma20_by_symbol=sma20_by_symbol,
    )
    # Live IBKR Canada paper is CAD; never invent USD when the broker tag is missing.
    if account_currency:
        ccy = str(account_currency).upper()
        if ccy == "BASE":
            ccy = "CAD"
    else:
        ccy = "CAD" if use_account_cash else "USD"
    return {
        "nav": nav,
        "cash": cash,
        "invested": invested,
        "invested_usd": invested_usd_marks,
        "accrued_cash": accrued,
        "available_funds": spendable_for_buys,
        "spendable_usd": spendable_for_shares,
        "trading_budget_usd": trading_budget_usd,
        "unused_budget_usd": unused_usd,
        "buy_pool_usd": buy_pool_usd,
        "withdrawable_usd": withdrawable_usd,
        "account_currency": ccy,
        "book_capital": start,
        "bot_return_pct": bot_return_pct,
        "day_delta": day_delta,
        "day_delta_pct": day_delta_pct,
        "edge": edge,
        "holdings": holdings,
        "starting_cash": start,
        "use_account_cash": use_account_cash,
        "status_line": book_status_line(book_positions, picker_active=picker_active),
        "orphan_dropped": max(0, len(positions or []) - len(book_positions)),
    }
