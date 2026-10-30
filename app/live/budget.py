"""Trading budget: wallet size for live buys (separate from full IBKR equity).

effective buy pool = min(max(0, budget - invested), spendable_usd)
Save+REBALANCE equalizes sleeves to budget/N (orders). Reduce is cash-out-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import Any, Mapping, Sequence


def invested_usd(
    positions: Mapping[str, float],
    prices: Mapping[str, float],
) -> float:
    """USD mark of current long stock (share prices are USD)."""
    total = 0.0
    for sym, qty in positions.items():
        shares = float(qty)
        if shares <= 1e-9:
            continue
        try:
            px = float(prices[sym])
        except (KeyError, TypeError, ValueError):
            continue
        if px > 0:
            total += shares * px
    return max(0.0, total)


def unused_budget(budget_usd: float, invested: float) -> float:
    """Room left in the wallet before cash clamp."""
    return max(0.0, float(budget_usd) - max(0.0, float(invested)))


def effective_buy_pool(
    budget_usd: float | None,
    *,
    invested_usd: float,
    spendable_usd: float,
) -> float:
    """USD available for new flat BUYs (raw unused, before equal-sleeve reserve).

    When ``budget_usd`` is None (legacy), fall back to full spendable (old
    whole-account behavior). Prefer seeding a budget so this path is unused.
    """
    spendable = max(0.0, float(spendable_usd))
    if budget_usd is None:
        return spendable
    unused = max(0.0, float(budget_usd) - max(0.0, float(invested_usd)))
    return min(unused, spendable)


def equal_sleeve_target_usd(budget_usd: float, n_symbols: int) -> float:
    """Per-sleeve equal target = budget / N."""
    n = int(n_symbols)
    if n <= 0:
        return 0.0
    return max(0.0, float(budget_usd)) / float(n)


def reserve_underweight_longs_usd(
    budget_usd: float,
    *,
    symbols: Sequence[str],
    positions: Mapping[str, float],
    prices: Mapping[str, float],
) -> float:
    """USD that must stay free to top underweight longs up to budget/N.

    Without this, flat signal buys spend the gap that belongs to names like P
    sitting at 70k of a 100k sleeve target.
    """
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    if not syms or float(budget_usd) <= 0:
        return 0.0
    target = equal_sleeve_target_usd(float(budget_usd), len(syms))
    reserved = 0.0
    for sym in syms:
        shares = float(positions.get(sym, 0.0) or 0.0)
        if shares <= 1e-9:
            continue
        try:
            px = float(prices[sym])
        except (KeyError, TypeError, ValueError):
            continue
        if px <= 0:
            continue
        gap = target - shares * px
        if gap > 1e-6:
            reserved += gap
    return reserved


def flat_buy_pool_usd(
    budget_usd: float | None,
    *,
    symbols: Sequence[str],
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    invested_usd: float,
    spendable_usd: float,
) -> float:
    """Signal-buy pool for flats after reserving underweight long top-ups."""
    raw = effective_buy_pool(
        budget_usd,
        invested_usd=invested_usd,
        spendable_usd=spendable_usd,
    )
    if budget_usd is None:
        return raw
    reserved = reserve_underweight_longs_usd(
        float(budget_usd),
        symbols=symbols,
        positions=positions,
        prices=prices,
    )
    return max(0.0, raw - reserved)


def withdrawable_cash_usd(
    *,
    cash_usd: float,
    budget_usd: float | None,
    invested_usd: float,
) -> float:
    """Rough IBKR cash not needed to support the current budget.

    After a reduce, invested <= budget; idle cash above that support is
    withdrawable. Conservative: cash minus max(0, budget - invested) reserved.
    """
    cash = max(0.0, float(cash_usd))
    if budget_usd is None:
        return 0.0
    reserved = max(0.0, float(budget_usd) - max(0.0, float(invested_usd)))
    return max(0.0, cash - reserved)


@dataclass(frozen=True)
class ReduceSell:
    symbol: str
    shares: float
    price: float
    notional: float


def plan_reduce_to_budget(
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    *,
    budget_usd: float,
    invested: float | None = None,
) -> list[ReduceSell]:
    """Whole-share SELLs to bring invested USD down to ``budget_usd``.

    Budget 0 → sell all longs. Otherwise pro-rata by current notional, rounded
    to whole shares (may leave a few dollars of residual over-invest).
    """
    target = max(0.0, float(budget_usd))
    longs: list[tuple[str, float, float, float]] = []
    for sym, qty in positions.items():
        shares = float(qty)
        if shares <= 1e-9:
            continue
        try:
            px = float(prices[sym])
        except (KeyError, TypeError, ValueError):
            continue
        if px <= 0:
            continue
        longs.append((str(sym), shares, px, shares * px))
    if not longs:
        return []
    current = float(invested) if invested is not None else sum(n for *_, n in longs)
    if current <= target + 1e-6:
        return []
    if target <= 1e-9:
        return [
            ReduceSell(symbol=sym, shares=shares, price=px, notional=shares * px)
            for sym, shares, px, _ in longs
        ]

    excess = current - target
    sells: list[ReduceSell] = []
    # First pass: pro-rata floor shares.
    planned: list[tuple[str, float, float, float]] = []  # sym, sell_shares, px, notional
    for sym, shares, px, notional in longs:
        weight = notional / current if current > 0 else 0.0
        raw_sell = excess * weight / px
        sell_shares = float(floor(raw_sell))
        sell_shares = min(sell_shares, shares)
        if sell_shares >= 1:
            planned.append((sym, sell_shares, px, sell_shares * px))
    sold = sum(n for *_, n in planned)
    # If still short of excess due to flooring, sell 1 more share from largest leftovers.
    remain = excess - sold
    if remain > px_eps(longs):
        leftovers = sorted(
            (
                (sym, shares, px, notional)
                for sym, shares, px, notional in longs
                if shares - _sold_shares(planned, sym) >= 1
            ),
            key=lambda row: -(row[3]),
        )
        for sym, shares, px, _ in leftovers:
            if remain <= 1e-6:
                break
            already = _sold_shares(planned, sym)
            if already + 1 > shares + 1e-9:
                continue
            planned = _bump_sell(planned, sym, px, already + 1.0)
            remain -= px
    for sym, sell_shares, px, notional in planned:
        if sell_shares >= 1:
            sells.append(
                ReduceSell(symbol=sym, shares=float(sell_shares), price=px, notional=notional)
            )
    return sells


def px_eps(longs: Sequence[tuple[str, float, float, float]]) -> float:
    if not longs:
        return 0.0
    return min(px for _, _, px, _ in longs) * 0.5


def _sold_shares(planned: Sequence[tuple[str, float, float, float]], symbol: str) -> float:
    for sym, sh, _, _ in planned:
        if sym == symbol:
            return float(sh)
    return 0.0


def _bump_sell(
    planned: list[tuple[str, float, float, float]],
    symbol: str,
    price: float,
    new_shares: float,
) -> list[tuple[str, float, float, float]]:
    out: list[tuple[str, float, float, float]] = []
    found = False
    for sym, sh, px, _ in planned:
        if sym == symbol:
            out.append((sym, new_shares, price, new_shares * price))
            found = True
        else:
            out.append((sym, sh, px, sh * px))
    if not found:
        out.append((symbol, new_shares, price, new_shares * price))
    return out


@dataclass(frozen=True)
class RebalanceOrder:
    symbol: str
    side: str  # "BUY" | "SELL"
    shares: float
    price: float
    notional: float
    target_usd: float
    current_usd: float


@dataclass(frozen=True)
class RebalanceSkip:
    symbol: str
    reason: str
    target_usd: float
    current_usd: float
    price: float | None = None


@dataclass(frozen=True)
class RebalancePlanResult:
    """Equal-sleeve rebalance plan (SELL overweight, BUY underweight)."""

    orders: list[RebalanceOrder] = field(default_factory=list)
    skipped: list[RebalanceSkip] = field(default_factory=list)
    target_per_sleeve: float = 0.0
    n_symbols: int = 0

    @property
    def sells(self) -> list[RebalanceOrder]:
        return [o for o in self.orders if o.side == "SELL"]

    @property
    def buys(self) -> list[RebalanceOrder]:
        return [o for o in self.orders if o.side == "BUY"]


def plan_rebalance_to_equal(
    symbols: Sequence[str],
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    *,
    budget_usd: float,
    spendable_usd: float,
    sma20_ok: Mapping[str, bool] | None = None,
) -> RebalancePlanResult:
    """Whole-share orders so each symbol targets ``budget_usd / N``.

    - Budget 0 → sell all listed longs; no buys.
    - Overweight → SELL down toward target (never below 0).
    - Underweight → BUY up toward target only when ``sma20_ok[sym]`` is True
      (missing key treated as False — fail closed). Never buy above target.
    - Total buy notional clamped to ``spendable_usd + sell proceeds``.
    - Missing / non-positive price → skip that symbol.
    Caller must pass non-``exit_only`` symbols only.
    """
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    # Preserve order, drop dupes.
    seen: set[str] = set()
    ordered: list[str] = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    n = len(ordered)
    if n == 0:
        return RebalancePlanResult()

    budget = max(0.0, float(budget_usd))
    spendable = max(0.0, float(spendable_usd))
    target = 0.0 if budget <= 1e-9 else budget / float(n)
    gate = {str(k).upper(): bool(v) for k, v in (sma20_ok or {}).items()}

    skipped: list[RebalanceSkip] = []
    sells: list[RebalanceOrder] = []
    buy_wants: list[RebalanceOrder] = []

    for sym in ordered:
        try:
            px = float(prices[sym])
        except (KeyError, TypeError, ValueError):
            skipped.append(
                RebalanceSkip(
                    symbol=sym,
                    reason="missing_price",
                    target_usd=target,
                    current_usd=0.0,
                )
            )
            continue
        if px <= 0:
            skipped.append(
                RebalanceSkip(
                    symbol=sym,
                    reason="invalid_price",
                    target_usd=target,
                    current_usd=0.0,
                    price=px,
                )
            )
            continue

        shares = max(0.0, float(positions.get(sym, 0.0) or 0.0))
        current = shares * px

        if budget <= 1e-9:
            if shares >= 1:
                sells.append(
                    RebalanceOrder(
                        symbol=sym,
                        side="SELL",
                        shares=float(floor(shares)),
                        price=px,
                        notional=float(floor(shares)) * px,
                        target_usd=0.0,
                        current_usd=current,
                    )
                )
            continue

        if current > target + 1e-6:
            excess = current - target
            sell_shares = min(float(floor(excess / px)), float(floor(shares)))
            if sell_shares >= 1:
                sells.append(
                    RebalanceOrder(
                        symbol=sym,
                        side="SELL",
                        shares=sell_shares,
                        price=px,
                        notional=sell_shares * px,
                        target_usd=target,
                        current_usd=current,
                    )
                )
            continue

        if current < target - 1e-6:
            if not gate.get(sym, False):
                skipped.append(
                    RebalanceSkip(
                        symbol=sym,
                        reason="sma20_gate",
                        target_usd=target,
                        current_usd=current,
                        price=px,
                    )
                )
                continue
            deficit = target - current
            buy_shares = float(floor(deficit / px))
            if buy_shares < 1:
                skipped.append(
                    RebalanceSkip(
                        symbol=sym,
                        reason="zero_quantity",
                        target_usd=target,
                        current_usd=current,
                        price=px,
                    )
                )
                continue
            buy_wants.append(
                RebalanceOrder(
                    symbol=sym,
                    side="BUY",
                    shares=buy_shares,
                    price=px,
                    notional=buy_shares * px,
                    target_usd=target,
                    current_usd=current,
                )
            )

    sell_proceeds = sum(o.notional for o in sells)
    available = spendable + sell_proceeds
    buys = _clamp_buys_to_cash(buy_wants, available)
    # Record cash-clamped drops as skips when a want became empty.
    bought_syms = {o.symbol for o in buys}
    for want in buy_wants:
        if want.symbol not in bought_syms:
            skipped.append(
                RebalanceSkip(
                    symbol=want.symbol,
                    reason="cash_clamp",
                    target_usd=want.target_usd,
                    current_usd=want.current_usd,
                    price=want.price,
                )
            )

    orders = list(sells) + list(buys)
    return RebalancePlanResult(
        orders=orders,
        skipped=skipped,
        target_per_sleeve=target,
        n_symbols=n,
    )


def _clamp_buys_to_cash(
    wants: Sequence[RebalanceOrder],
    available_usd: float,
) -> list[RebalanceOrder]:
    """Shrink whole-share BUY legs until notional fits ``available_usd``."""
    cash = max(0.0, float(available_usd))
    if not wants or cash <= 1e-9:
        return []
    # Mutable working set: symbol -> shares, price, meta
    work: list[list[Any]] = [
        [o.symbol, float(o.shares), float(o.price), float(o.target_usd), float(o.current_usd)]
        for o in wants
    ]
    while True:
        total = sum(sh * px for _, sh, px, _, _ in work if sh >= 1)
        if total <= cash + 1e-6:
            break
        # Drop 1 share from the largest notional leg.
        candidates = [(i, sh * px) for i, (_, sh, px, _, _) in enumerate(work) if sh >= 1]
        if not candidates:
            break
        i, _ = max(candidates, key=lambda row: row[1])
        work[i][1] -= 1.0

    out: list[RebalanceOrder] = []
    for sym, sh, px, tgt, cur in work:
        if sh < 1:
            continue
        out.append(
            RebalanceOrder(
                symbol=sym,
                side="BUY",
                shares=sh,
                price=px,
                notional=sh * px,
                target_usd=tgt,
                current_usd=cur,
            )
        )
    return out
