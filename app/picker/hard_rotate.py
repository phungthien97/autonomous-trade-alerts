"""Hard rotate: flatten the whole bot book, then enter the new slate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardRotateFlags:
    exit_only: bool
    awaiting_first_buy: bool


@dataclass(frozen=True)
class HardRotatePlan:
    """Diff for a full cutover.

    - target (pending): all get awaiting_first_buy (even names that were kept —
      they are sold in the flatten phase, then re-entered under SMA20).
    - dropped (prior only): exit_only until flat, then pruned.
    - phase starts as ``flattening``; worker flips to ``idle`` once bot book is flat.
    """

    kept: list[str]
    added: list[str]
    dropped: list[str]
    target: list[str]
    flags: dict[str, HardRotateFlags]


def plan_hard_rotate(
    active_symbols: list[str],
    pending_symbols: list[str],
) -> HardRotatePlan:
    active = list(dict.fromkeys(active_symbols))
    pending = list(dict.fromkeys(pending_symbols))
    active_set = set(active)
    pending_set = set(pending)

    kept = [s for s in pending if s in active_set]
    added = [s for s in pending if s not in active_set]
    dropped = [s for s in active if s not in pending_set]

    flags: dict[str, HardRotateFlags] = {}
    for symbol in pending:
        # Every target re-enters via first-buy / SMA path after flatten.
        flags[symbol] = HardRotateFlags(exit_only=False, awaiting_first_buy=True)
    for symbol in dropped:
        flags[symbol] = HardRotateFlags(exit_only=True, awaiting_first_buy=False)

    return HardRotatePlan(
        kept=kept,
        added=added,
        dropped=dropped,
        target=pending,
        flags=flags,
    )
