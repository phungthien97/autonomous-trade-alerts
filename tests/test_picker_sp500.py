from pathlib import Path

import pytest

from app.picker.sp500 import Sp500LoadError, load_sp500, parse_sp500_html

FIXTURE = Path(__file__).parent / "fixtures" / "sp500_wikipedia_sample.html"


def test_parse_sp500_html_fixture() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    tickers = parse_sp500_html(html)
    assert tickers == ["AAPL", "BF B", "BRK B", "MSFT"]


def test_load_sp500_writes_cache_on_success(tmp_path: Path) -> None:
    cache = tmp_path / "sp500_cache.json"
    html = FIXTURE.read_text(encoding="utf-8")
    tickers = load_sp500(cache, fetcher=lambda: html)
    assert tickers == ["AAPL", "BF B", "BRK B", "MSFT"]
    assert cache.is_file()
    assert "BRK B" in cache.read_text(encoding="utf-8")


def test_load_sp500_uses_last_good_when_fetch_fails(tmp_path: Path) -> None:
    cache = tmp_path / "sp500_cache.json"
    html = FIXTURE.read_text(encoding="utf-8")
    load_sp500(cache, fetcher=lambda: html)

    def boom() -> str:
        raise ConnectionError("wikipedia down")

    tickers = load_sp500(cache, fetcher=boom)
    assert tickers == ["AAPL", "BF B", "BRK B", "MSFT"]


def test_load_sp500_raises_when_fetch_fails_and_no_cache(tmp_path: Path) -> None:
    cache = tmp_path / "missing" / "sp500_cache.json"

    def boom() -> str:
        raise ConnectionError("wikipedia down")

    with pytest.raises(Sp500LoadError, match="no last-good cache"):
        load_sp500(cache, fetcher=boom)
