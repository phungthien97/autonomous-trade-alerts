from app.audit import AuditLog
from app.broker import InMemoryBroker
from app.live import PendingIntentStore
from app.live.executor import execute_intent
from app.live.idempotency import IdempotencyStore
from app.live.modes import TradingMode
from app.live.planner import OrderIntent


def _intent() -> OrderIntent:
    return OrderIntent("AAPL", "BUY", 1.0, 0.4, "bar-1", "test")


def test_dry_run_does_not_change_positions(tmp_path) -> None:
    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 100.0})
    result = execute_intent(
        _intent(),
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.live_dry_run,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert result.status == "dry_run"
    assert broker.get_positions() == {}


def test_live_mode_changes_positions(tmp_path) -> None:
    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 100.0})
    result = execute_intent(
        _intent(),
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.live,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert result.status == "filled"
    assert broker.get_positions()["AAPL"] == 1.0


def test_outside_rth_queues(tmp_path) -> None:
    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 100.0})
    queue = PendingIntentStore(tmp_path / "q.json")
    audit = AuditLog(tmp_path / "a.jsonl")
    result = execute_intent(
        _intent(),
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        audit,
        TradingMode.live,
        False,
        queue,
    )
    assert result.status == "queued"
    assert broker.get_positions() == {}
    assert len(queue.list_pending()) == 1
    assert queue.list_pending()[0].quantity == 1.0
    # Second park of the same intent must not spam another audit row.
    second = execute_intent(
        _intent(),
        broker,
        IdempotencyStore(tmp_path / "id2.json"),
        audit,
        TradingMode.live,
        False,
        queue,
    )
    assert second.status == "queued"
    assert len(queue.list_pending()) == 1
    queued_events = [e for e in audit.read_all() if e["event_type"] == "queued"]
    assert len(queued_events) == 1


def test_flush_pending_queue_executes(tmp_path) -> None:
    from app.live.executor import flush_pending_queue

    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 100.0})
    queue = PendingIntentStore(tmp_path / "q.json")
    idem = IdempotencyStore(tmp_path / "id.json")
    audit = AuditLog(tmp_path / "a.jsonl")
    execute_intent(_intent(), broker, idem, audit, TradingMode.live, False, queue)
    assert len(queue.list_pending()) == 1
    results = flush_pending_queue(
        queue,
        broker=broker,
        idempotency=idem,
        audit=audit,
        mode=TradingMode.live,
    )
    assert results[0]["status"] == "filled"
    assert broker.get_positions().get("AAPL") == 1.0
    assert queue.list_pending() == []


def test_flush_respects_gate(tmp_path) -> None:
    from app.live.executor import flush_pending_queue

    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 100.0})
    queue = PendingIntentStore(tmp_path / "q.json")
    idem = IdempotencyStore(tmp_path / "id.json")
    audit = AuditLog(tmp_path / "a.jsonl")
    execute_intent(_intent(), broker, idem, audit, TradingMode.live, False, queue)
    results = flush_pending_queue(
        queue,
        broker=broker,
        idempotency=idem,
        audit=audit,
        mode=TradingMode.live,
        allow_side=lambda _row: "exit_only",
    )
    assert results[0]["status"] == "dropped"
    assert broker.get_positions() == {}
    assert queue.list_pending() == []


def test_duplicate_skipped(tmp_path) -> None:
    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 100.0})
    idem = IdempotencyStore(tmp_path / "id.json")
    audit = AuditLog(tmp_path / "a.jsonl")
    queue = PendingIntentStore(tmp_path / "q.json")
    execute_intent(_intent(), broker, idem, audit, TradingMode.live, True, queue)
    cash_after = broker.get_account_snapshot().cash_usd
    second = execute_intent(_intent(), broker, idem, audit, TradingMode.live, True, queue)
    assert second.status == "skipped"
    assert broker.get_account_snapshot().cash_usd == cash_after


def test_sell_skipped_when_broker_flat(tmp_path) -> None:
    broker = InMemoryBroker(1000.0, last_prices={"AMGN": 440.0})
    intent = OrderIntent("AMGN", "SELL", 504.0, 1.0, "bar-sell", "test")
    result = execute_intent(
        intent,
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.broker_paper,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert result.status == "skipped"
    assert broker.get_positions() == {}


def test_sell_capped_to_broker_long(tmp_path) -> None:
    broker = InMemoryBroker(0.0, positions={"AMGN": 100.0}, last_prices={"AMGN": 440.0})
    intent = OrderIntent("AMGN", "SELL", 504.0, 1.0, "bar-sell-2", "test")
    result = execute_intent(
        intent,
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.broker_paper,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert result.status == "filled"
    assert broker.get_positions().get("AMGN", 0.0) == 0.0
