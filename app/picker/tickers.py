"""Normalize Wikipedia/Yahoo-style tickers to IBKR US equity symbols.

IBKR class shares use a space (e.g. ``BRK B``), while Wikipedia lists them
with a dot (``BRK.B``). Yahoo often uses a hyphen (``BRK-B``). This module
maps those forms to the IBKR convention used by ``Stock(symbol, "SMART", "USD")``.
"""

from __future__ import annotations


def normalize_wikipedia_ticker(raw: str) -> str:
    """Return an IBKR-friendly US ticker, or ``""`` if empty after cleaning."""
    text = str(raw).strip().upper()
    if not text:
        return ""
    # Class shares: BRK.B / BRK-B → BRK B
    if "." in text:
        text = text.replace(".", " ")
    elif "-" in text:
        text = text.replace("-", " ")
    # Collapse accidental double spaces
    return " ".join(text.split())


def normalize_list(tickers: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Normalize, drop empties, dedupe, and return a sorted list."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tickers:
        symbol = normalize_wikipedia_ticker(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return sorted(out)
