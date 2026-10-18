"""Bulk IBKR fetch failure policy for picker ranking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FetchFailureEvaluation:
    abort: bool
    failure_pct: float
    total_symbols: int
    failed_or_skipped: int


def evaluate_fetch_failures(
    total_symbols: int,
    failed_or_skipped: int,
    threshold: float = 0.30,
) -> FetchFailureEvaluation:
    """Abort when failed/skipped ratio is **strictly greater than** ``threshold``.

    Exact 30% (ratio == 0.30) proceeds. Zero total → abort (nothing to rank).
    """
    if total_symbols < 0 or failed_or_skipped < 0:
        raise ValueError("counts must be non-negative")
    if failed_or_skipped > total_symbols and total_symbols > 0:
        raise ValueError("failed_or_skipped cannot exceed total_symbols")
    if total_symbols == 0:
        return FetchFailureEvaluation(
            abort=True,
            failure_pct=1.0,
            total_symbols=0,
            failed_or_skipped=failed_or_skipped,
        )
    failure_pct = failed_or_skipped / total_symbols
    return FetchFailureEvaluation(
        abort=failure_pct > threshold,
        failure_pct=failure_pct,
        total_symbols=total_symbols,
        failed_or_skipped=failed_or_skipped,
    )
