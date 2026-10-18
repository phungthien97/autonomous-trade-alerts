"""Email bodies for picker ranking success / failure."""

from __future__ import annotations

from typing import Sequence

from app.notifier import send_signal_email
from app.picker.rank import SelectedSymbol


def build_success_email_body(
    *,
    run_id: str,
    as_of: str,
    opt_window: str,
    score_window: str,
    selected: Sequence[SelectedSymbol],
    active_symbols: Sequence[str],
    skipped: Sequence[tuple[str, str]],
    failure_pct: float,
    apply_after: str,
    dry_run: bool = False,
) -> str:
    selected_syms = [s.symbol for s in selected]
    added = sorted(set(selected_syms) - set(active_symbols))
    dropped = sorted(set(active_symbols) - set(selected_syms))
    lines = [
        f"Run ID: {run_id}",
        f"As of: {as_of}",
        f"Optimize window: {opt_window}",
        f"Score window: {score_window}",
        f"Dry run: {dry_run}",
        f"Skip rate: {failure_pct:.1%} ({len(skipped)} skipped)",
        f"Apply after: {apply_after} (first live-worker cycle after Monday open)",
        "",
        "Selected (edge >= 0, top <= 5):",
    ]
    if not selected:
        lines.append("  (none — all cash)")
    for row in selected:
        lines.append(
            f"  {row.symbol}: edge={row.edge:.4f} strat={row.strategy_return:.4f} "
            f"bh={row.bh_return if row.bh_return is not None else 'n/a'} "
            f"buy={row.buy_rise:.4f} sell={row.sell_drop:.4f}"
        )
    lines.extend(
        [
            "",
            f"Adds vs active: {', '.join(added) if added else '(none)'}",
            f"Drops vs active: {', '.join(dropped) if dropped else '(none)'}",
            f"First run / empty previous: {not bool(active_symbols)}",
        ]
    )
    if skipped:
        sample = ", ".join(f"{s}:{r}" for s, r in list(skipped)[:10])
        lines.append(f"Skip sample: {sample}")
    return "\n".join(lines) + "\n"


def build_failure_email_body(
    *,
    run_id: str,
    as_of: str,
    skipped: Sequence[tuple[str, str]],
    failure_pct: float,
    total_symbols: int,
) -> str:
    sample = ", ".join(f"{s}:{r}" for s, r in list(skipped)[:15])
    return (
        f"Run ID: {run_id}\n"
        f"As of: {as_of}\n"
        f"ABORT: IBKR fetch failure {failure_pct:.1%} "
        f"({len(skipped)}/{total_symbols}) exceeds 30% threshold.\n"
        f"Kept previous list — pending_selection NOT overwritten.\n"
        f"Skip sample: {sample}\n"
    )


def send_picker_email(subject: str, body: str) -> bool:
    return send_signal_email(subject, body)
