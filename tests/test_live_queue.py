from app.live import PendingIntent, PendingIntentStore


def test_enqueue_dedupes_and_persists(tmp_path) -> None:
    path = tmp_path / "queue.json"
    store = PendingIntentStore(path)
    intent = PendingIntent("AAPL", "BUY", "2026-09-23T14:30:00Z", "2026-09-23T20:00:00Z", "signal")
    assert store.enqueue(intent) is True
    assert store.enqueue(intent) is False
    reloaded = PendingIntentStore(path)
    pending = reloaded.list_pending()
    assert len(pending) == 1
    assert pending[0].symbol == "AAPL"


def test_pop_symbol_removes_only_that_symbol(tmp_path) -> None:
    store = PendingIntentStore(tmp_path / "queue.json")
    store.enqueue(PendingIntent("AAPL", "BUY", "b1", "t", "r"))
    store.enqueue(PendingIntent("MSFT", "SELL", "b1", "t", "r"))
    popped = store.pop_symbol("AAPL")
    assert [row.symbol for row in popped] == ["AAPL"]
    assert [row.symbol for row in store.list_pending()] == ["MSFT"]
    store.clear()
    assert store.list_pending() == []
