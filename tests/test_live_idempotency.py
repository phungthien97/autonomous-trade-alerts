from app.live import IdempotencyStore, intent_key


def test_mark_and_reload(tmp_path) -> None:
    path = tmp_path / "idem.json"
    store = IdempotencyStore(path)
    key = intent_key("AAPL", "2026-09-23T14:30:00Z", "BUY")
    other = intent_key("AAPL", "2026-09-23T15:30:00Z", "BUY")
    assert store.already_done(key) is False
    store.mark_done(key, {"order_id": "1"})
    assert store.already_done(key) is True
    assert store.already_done(other) is False
    reloaded = IdempotencyStore(path)
    assert reloaded.already_done(key) is True
    assert key in reloaded.list_keys()
