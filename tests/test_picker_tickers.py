from app.picker.tickers import normalize_list, normalize_wikipedia_ticker


def test_normalize_class_shares_dot_to_space() -> None:
    assert normalize_wikipedia_ticker("BRK.B") == "BRK B"
    assert normalize_wikipedia_ticker("BF.B") == "BF B"
    assert normalize_wikipedia_ticker(" brk.b ") == "BRK B"


def test_normalize_class_shares_hyphen_to_space() -> None:
    assert normalize_wikipedia_ticker("BRK-B") == "BRK B"


def test_normalize_plain_ticker() -> None:
    assert normalize_wikipedia_ticker("aapl") == "AAPL"
    assert normalize_wikipedia_ticker("") == ""
    assert normalize_wikipedia_ticker("   ") == ""


def test_normalize_list_dedupes_sorts_and_drops_empty() -> None:
    assert normalize_list(["MSFT", "aapl", "", "MSFT", "BRK.B", "  "]) == [
        "AAPL",
        "BRK B",
        "MSFT",
    ]
