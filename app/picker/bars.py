"""Hourly bar providers and universe fetch for picker ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping, Protocol, Sequence

from app.picker.failures import evaluate_fetch_failures
from app.picker.windows import DateWindow, filter_hourly_closes


class SkipSymbol(Exception):
    """Symbol could not be fetched after retries."""

    def __init__(self, symbol: str, reason: str = "fetch_failed") -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"{symbol}: {reason}")


class HourlyBarProvider(Protocol):
    def get_hourly_closes(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> Sequence[tuple[datetime | date, float]]:
        """Return ``(timestamp, close)`` bars covering ``[start, end]`` dates."""


@dataclass
class FixtureBarProvider:
    """In-memory provider for unit tests."""

    series: Mapping[str, Sequence[tuple[datetime | date, float]]]
    fail_symbols: set[str] = field(default_factory=set)

    def get_hourly_closes(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> Sequence[tuple[datetime | date, float]]:
        if symbol in self.fail_symbols:
            raise ConnectionError(f"fixture fail for {symbol}")
        if symbol not in self.series:
            raise KeyError(f"no fixture bars for {symbol}")
        timestamps = [row[0] for row in self.series[symbol]]
        closes = [float(row[1]) for row in self.series[symbol]]
        ts_out, px_out = filter_hourly_closes(timestamps, closes, start, end)
        return list(zip(ts_out, px_out))


def fetch_symbol_with_retries(
    provider: HourlyBarProvider,
    symbol: str,
    start: date,
    end: date,
    attempts: int = 3,
) -> list[tuple[datetime | date, float]]:
    """Fetch bars; retry transient errors; raise ``SkipSymbol`` when exhausted."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            rows = list(provider.get_hourly_closes(symbol, start, end))
            return rows
        except SkipSymbol:
            raise
        except Exception as exc:  # noqa: BLE001 — retry then skip
            last_exc = exc
    reason = type(last_exc).__name__ if last_exc else "fetch_failed"
    raise SkipSymbol(symbol, reason=reason)


@dataclass(frozen=True)
class SymbolWindowCloses:
    opt_closes: list[float]
    score_closes: list[float]


@dataclass(frozen=True)
class UniverseBarsResult:
    ok: dict[str, SymbolWindowCloses]
    skipped: list[tuple[str, str]]
    abort: bool
    failure_pct: float


def fetch_universe_bars(
    symbols: Sequence[str],
    provider: HourlyBarProvider,
    opt_window: DateWindow,
    score_window: DateWindow,
    attempts: int = 3,
    fail_threshold: float = 0.30,
) -> UniverseBarsResult:
    """Fetch opt+score closes per symbol; abort when skip rate > threshold."""
    ok: dict[str, SymbolWindowCloses] = {}
    skipped: list[tuple[str, str]] = []
    # Fetch once over the full span covering both windows.
    span_start = min(opt_window.start, score_window.start)
    span_end = max(opt_window.end, score_window.end)

    total = len(symbols)
    for i, symbol in enumerate(symbols, start=1):
        if i == 1 or i % 25 == 0 or i == total:
            print(f"picker_fetch {i}/{total} symbol={symbol}", flush=True)
        try:
            rows = fetch_symbol_with_retries(
                provider, symbol, span_start, span_end, attempts=attempts
            )
            timestamps = [r[0] for r in rows]
            closes = [float(r[1]) for r in rows]
            _, opt_closes = filter_hourly_closes(
                timestamps, closes, opt_window.start, opt_window.end
            )
            _, score_closes = filter_hourly_closes(
                timestamps, closes, score_window.start, score_window.end
            )
            if len(opt_closes) < 2 or len(score_closes) < 2:
                skipped.append((symbol, "insufficient_bars"))
                continue
            ok[symbol] = SymbolWindowCloses(
                opt_closes=opt_closes,
                score_closes=score_closes,
            )
        except SkipSymbol as exc:
            skipped.append((symbol, exc.reason))

    evaluation = evaluate_fetch_failures(
        total_symbols=len(symbols),
        failed_or_skipped=len(skipped),
        threshold=fail_threshold,
    )
    return UniverseBarsResult(
        ok=ok,
        skipped=skipped,
        abort=evaluation.abort,
        failure_pct=evaluation.failure_pct,
    )
