"""S&P 500 constituents from Wikipedia HTML with last-good disk cache."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from app.picker.tickers import normalize_list


class Sp500LoadError(RuntimeError):
    """Raised when Wikipedia fetch fails and no last-good cache exists."""


class _ConstituentsTableParser(HTMLParser):
    """Extract first-column symbols from ``<table id="constituents">``."""

    def __init__(self) -> None:
        super().__init__()
        self.symbols: list[str] = []
        self._in_constituents = False
        self._table_depth = 0
        self._in_row = False
        self._in_first_cell = False
        self._cell_index = 0
        self._capture = False
        self._buf: list[str] = []

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
            self._cell_index = 0
            return
        if self._in_row and tag in {"td", "th"}:
            self._in_first_cell = self._cell_index == 0
            self._capture = self._in_first_cell and tag == "td"
            self._buf = []
            self._cell_index += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_constituents:
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_constituents = False
                self._table_depth = 0
            return
        if not self._in_constituents:
            return
        if tag in {"td", "th"} and self._in_first_cell:
            if self._capture:
                text = "".join(self._buf).strip()
                if text and text.lower() != "symbol":
                    self.symbols.append(text)
            self._in_first_cell = False
            self._capture = False
            self._buf = []
        elif tag == "tr":
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)


def parse_sp500_html(html: str) -> list[str]:
    """Parse Wikipedia constituents HTML into a normalized ticker list."""
    parser = _ConstituentsTableParser()
    parser.feed(html)
    return normalize_list(parser.symbols)


def _read_cache(cache_path: Path) -> list[str] | None:
    if not cache_path.is_file():
        return None
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    tickers = raw.get("tickers")
    if not isinstance(tickers, list):
        return None
    return normalize_list([str(t) for t in tickers])


def _write_cache(cache_path: Path, tickers: list[str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tickers": tickers,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(cache_path)


def load_sp500(cache_path: Path, fetcher: Callable[[], str]) -> list[str]:
    """Fetch+parse S&P list; on failure return last-good cache or raise."""
    try:
        html = fetcher()
        tickers = parse_sp500_html(html)
        if not tickers:
            raise Sp500LoadError("Parsed S&P 500 list is empty")
        _write_cache(cache_path, tickers)
        return tickers
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
