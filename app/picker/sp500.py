"""S&P 500 constituents from Wikipedia HTML with last-good disk cache."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Mapping

from app.picker.tickers import normalize_list, normalize_wikipedia_ticker


class Sp500LoadError(RuntimeError):
    """Raised when Wikipedia fetch fails and no last-good cache exists."""


@dataclass(frozen=True)
class Sp500Constituent:
    symbol: str
    name: str = ""
    sector: str = ""


class _ConstituentsTableParser(HTMLParser):
    """Extract Symbol / Security / GICS Sector from ``<table id="constituents">``."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_constituents = False
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._buf: list[str] = []
        self._cells: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if tag == "table":
            if attr_map.get("id") == "constituents" or self._in_constituents:
                if attr_map.get("id") == "constituents":
                    self._in_constituents = True
                if self._in_constituents:
                    self._table_depth += 1
            return
        if not self._in_constituents:
            return
        if tag == "tr":
            self._in_row = True
            self._cells = []
            return
        if self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_constituents:
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_constituents = False
                self._table_depth = 0
            return
        if not self._in_constituents:
            return
        if tag in {"td", "th"} and self._in_cell:
            self._cells.append("".join(self._buf).strip())
            self._in_cell = False
            self._buf = []
        elif tag == "tr" and self._in_row:
            if self._cells:
                self.rows.append(self._cells)
            self._in_row = False
            self._cells = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf.append(data)


def parse_sp500_constituents(html: str) -> list[Sp500Constituent]:
    """Parse Wikipedia constituents into symbol + name + sector rows."""
    parser = _ConstituentsTableParser()
    parser.feed(html)
    out: list[Sp500Constituent] = []
    seen: set[str] = set()
    for cells in parser.rows:
        if not cells:
            continue
        raw_symbol = cells[0]
        if raw_symbol.lower() == "symbol":
            continue
        symbol = normalize_wikipedia_ticker(raw_symbol)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        name = cells[1].strip() if len(cells) > 1 else ""
        sector = cells[2].strip() if len(cells) > 2 else ""
        out.append(Sp500Constituent(symbol=symbol, name=name, sector=sector))
    out.sort(key=lambda c: c.symbol)
    return out


def parse_sp500_html(html: str) -> list[str]:
    """Parse Wikipedia constituents HTML into a normalized ticker list."""
    return [c.symbol for c in parse_sp500_constituents(html)]


def profiles_by_symbol(constituents: list[Sp500Constituent]) -> dict[str, Sp500Constituent]:
    return {c.symbol: c for c in constituents}


def _constituents_from_cache_payload(raw: Mapping[str, object]) -> list[Sp500Constituent] | None:
    rows = raw.get("constituents")
    if isinstance(rows, list) and rows:
        out: list[Sp500Constituent] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = normalize_wikipedia_ticker(str(row.get("symbol", "")))
            if not symbol:
                continue
            out.append(
                Sp500Constituent(
                    symbol=symbol,
                    name=str(row.get("name") or "").strip(),
                    sector=str(row.get("sector") or "").strip(),
                )
            )
        if out:
            return sorted(out, key=lambda c: c.symbol)
    tickers = raw.get("tickers")
    if isinstance(tickers, list):
        return [
            Sp500Constituent(symbol=s)
            for s in normalize_list([str(t) for t in tickers])
        ]
    return None


def _read_cache(cache_path: Path) -> list[Sp500Constituent] | None:
    if not cache_path.is_file():
        return None
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return _constituents_from_cache_payload(raw)


def _write_cache(cache_path: Path, constituents: list[Sp500Constituent]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tickers": [c.symbol for c in constituents],
        "constituents": [asdict(c) for c in constituents],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(cache_path)


def load_sp500_constituents(
    cache_path: Path, fetcher: Callable[[], str]
) -> list[Sp500Constituent]:
    """Fetch+parse S&P list with names/sectors; on failure return last-good cache."""
    try:
        html = fetcher()
        constituents = parse_sp500_constituents(html)
        if not constituents:
            raise Sp500LoadError("Parsed S&P 500 list is empty")
        _write_cache(cache_path, constituents)
        return constituents
    except Sp500LoadError:
        cached = _read_cache(cache_path)
        if cached:
            return cached
        raise
    except Exception as exc:
        cached = _read_cache(cache_path)
        if cached:
            return cached
        raise Sp500LoadError(
            f"S&P 500 fetch failed and no last-good cache at {cache_path}"
        ) from exc


def load_sp500(cache_path: Path, fetcher: Callable[[], str]) -> list[str]:
    """Fetch+parse S&P list; on failure return last-good cache or raise."""
    return [c.symbol for c in load_sp500_constituents(cache_path, fetcher)]


def load_sp500_profiles(cache_path: Path) -> dict[str, Sp500Constituent]:
    """Read symbol → name/sector from disk cache (no network)."""
    cached = _read_cache(cache_path)
    if not cached:
        return {}
    return profiles_by_symbol(cached)
