"""Monday apply orchestrator: pending → live + V1 + V2 + active."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.live.config import load_live_config
from app.paths import LivePaths, PickerPaths, StatePaths
from app.picker.active import ActiveSelection, ActiveSymbol, load_active, save_active
from app.picker.apply_live import apply_allocated_cash_to_live_state, apply_to_live_config
from app.picker.apply_paper import apply_to_paper_v1, apply_to_paper_v2
from app.picker.pending import load_pending, mark_applied
from app.picker.soft_rotate import plan_soft_rotate


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    reason: str
    run_id: str | None = None


def pending_is_stale(computed_at: str, now: datetime, max_age_days: int = 3) -> bool:
    try:
        computed = datetime.fromisoformat(computed_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if computed.tzinfo is None:
        computed = computed.replace(tzinfo=timezone.utc)
    return (now - computed.astimezone(timezone.utc)) > timedelta(days=max_age_days)


def maybe_apply_pending(
    picker_paths: PickerPaths,
    live_paths: LivePaths,
    v1_paths: StatePaths,
    v2_paths: StatePaths,
    now: datetime,
    *,
    rth_ok: bool,
) -> ApplyResult:
    """Apply pending when RTH and ``now >= apply_after``; else no-op / stale flag."""
    pending = load_pending(picker_paths.pending_selection_path)
    if pending is None:
        return ApplyResult(applied=False, reason="no_pending")
    if pending.status != "pending":
        return ApplyResult(applied=False, reason=f"status:{pending.status}", run_id=pending.run_id)
    try:
        apply_after = datetime.fromisoformat(pending.apply_after.replace("Z", "+00:00"))
    except ValueError:
        return ApplyResult(applied=False, reason="bad_apply_after", run_id=pending.run_id)
    if apply_after.tzinfo is None:
        apply_after = apply_after.replace(tzinfo=timezone.utc)
    if now.astimezone(timezone.utc) < apply_after.astimezone(timezone.utc):
        reason = "before_apply_after"
        if pending_is_stale(pending.computed_at, now):
            reason = "stale_pending_before_apply"
        return ApplyResult(applied=False, reason=reason, run_id=pending.run_id)
    if not rth_ok:
        reason = "outside_rth"
        if pending_is_stale(pending.computed_at, now):
            reason = "stale_pending_outside_rth"
        return ApplyResult(applied=False, reason=reason, run_id=pending.run_id)
    return apply_pending_selection(picker_paths, live_paths, v1_paths, v2_paths, now=now)


def apply_pending_selection(
    picker_paths: PickerPaths,
    live_paths: LivePaths,
    v1_paths: StatePaths,
    v2_paths: StatePaths,
    now: datetime | None = None,
) -> ApplyResult:
    """Apply pending selection to all targets; idempotent on status.

    Writes live/V1/V2 first, then active store, then marks pending applied.
    If a write raises, pending stays ``pending`` for retry.
    """
    pending = load_pending(picker_paths.pending_selection_path)
    if pending is None:
        return ApplyResult(applied=False, reason="no_pending")
    if pending.status == "applied":
        return ApplyResult(applied=False, reason="already_applied", run_id=pending.run_id)
    if pending.status == "aborted":
        return ApplyResult(applied=False, reason="aborted", run_id=pending.run_id)
    if pending.status != "pending":
        return ApplyResult(applied=False, reason=f"bad_status:{pending.status}", run_id=pending.run_id)

    prior = load_active(picker_paths.active_selection_path)
    active_symbols = [s.symbol for s in prior.symbols] if prior else []
    pending_symbols = [s.symbol for s in pending.symbols]
    prior_params = {s.symbol: s for s in (prior.symbols if prior else [])}
    prior_awaiting = {
        s.symbol: bool(s.awaiting_first_buy) for s in (prior.symbols if prior else [])
    }
    plan = plan_soft_rotate(
        active_symbols,
        pending_symbols,
        prior_awaiting=prior_awaiting,
    )
    awaiting_symbols = [
        sym for sym in pending_symbols if plan.flags[sym].awaiting_first_buy
    ]
    applied_at = (now or datetime.now(timezone.utc)).isoformat()

    apply_to_live_config(
        live_paths.config_path,
        pending.symbols,
        extra_symbols=plan.dropped,
    )
    live_total = None
    if live_paths.config_path.is_file():
        try:
            live_cfg = load_live_config(live_paths.config_path)
            if live_cfg.trading_budget_usd is not None:
                live_total = float(live_cfg.trading_budget_usd)
            else:
                live_total = float(live_cfg.total_cash)
        except (OSError, TypeError, ValueError, KeyError):
            live_total = None
    apply_allocated_cash_to_live_state(
        live_paths.state_path,
        pending.symbols,
        equal_fallback_total=live_total,
    )
    apply_to_paper_v1(
        v1_paths.config_path,
        v1_paths.state_path,
        pending.symbols,
        exit_only_symbols=plan.dropped,
        awaiting_first_buy=awaiting_symbols,
    )
    apply_to_paper_v2(
        v2_paths.config_path,
        v2_paths.state_path,
        pending.symbols,
        exit_only_symbols=plan.dropped,
        awaiting_first_buy=awaiting_symbols,
    )

    active_rows: list[ActiveSymbol] = []
    pending_by_symbol = {s.symbol: s for s in pending.symbols}
    for symbol in pending_symbols:
        src = pending_by_symbol[symbol]
        flags = plan.flags[symbol]
        joined = applied_at if symbol in plan.added else (
            prior_params[symbol].joined_at if symbol in prior_params else applied_at
        )
        active_rows.append(
            ActiveSymbol(
                symbol=symbol,
                buy_rise=src.buy_rise,
                sell_drop=src.sell_drop,
                exit_only=flags.exit_only,
                awaiting_first_buy=flags.awaiting_first_buy,
                joined_at=joined,
            )
        )
    for symbol in plan.dropped:
        flags = plan.flags[symbol]
        prior_row = prior_params.get(symbol)
        active_rows.append(
            ActiveSymbol(
                symbol=symbol,
                buy_rise=prior_row.buy_rise if prior_row else 0.02,
                sell_drop=prior_row.sell_drop if prior_row else 0.04,
                exit_only=flags.exit_only,
                awaiting_first_buy=False,
                joined_at=prior_row.joined_at if prior_row else None,
            )
        )

    save_active(
        picker_paths.active_selection_path,
        ActiveSelection(applied_at=applied_at, run_id=pending.run_id, symbols=active_rows),
    )
    mark_applied(picker_paths.pending_selection_path)
    return ApplyResult(applied=True, reason="applied", run_id=pending.run_id)
