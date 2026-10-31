"""Pure soft-rotate plan from active vs pending symbol sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SoftRotateFlags:
    exit_only: bool
    awaiting_first_buy: bool


@dataclass(frozen=True)
class SoftRotatePlan:
    kept: list[str]
    added: list[str]
    dropped: list[str]
    flags: dict[str, SoftRotateFlags]


def plan_soft_rotate(
    active_symbols: list[str],
    pending_symbols: list[str],
    *,
    prior_awaiting: Mapping[str, bool] | None = None,
) -> SoftRotatePlan:
    """Diff active vs pending and assign soft-rotate flags.

    - dropped → exit_only=True (sell on next sell; no new buys)
    - added → awaiting_first_buy=True (MA gate on first entry)
    - kept → preserve prior awaiting_first_buy until a real fill clears it
      (do NOT clear the SMA20 gate just because the name was re-picked)
    """
    active = list(dict.fromkeys(active_symbols))
    pending = list(dict.fromkeys(pending_symbols))
    active_set = set(active)
    pending_set = set(pending)
    prior = {str(k): bool(v) for k, v in (prior_awaiting or {}).items()}

    kept = [s for s in pending if s in active_set]
    added = [s for s in pending if s not in active_set]
    dropped = [s for s in active if s not in pending_set]

    flags: dict[str, SoftRotateFlags] = {}
    for symbol in kept:
        flags[symbol] = SoftRotateFlags(
            exit_only=False,
            awaiting_first_buy=bool(prior.get(symbol, False)),
        )
    for symbol in added:
        flags[symbol] = SoftRotateFlags(exit_only=False, awaiting_first_buy=True)
    for symbol in dropped:
        flags[symbol] = SoftRotateFlags(exit_only=True, awaiting_first_buy=False)

    return SoftRotatePlan(kept=kept, added=added, dropped=dropped, flags=flags)
