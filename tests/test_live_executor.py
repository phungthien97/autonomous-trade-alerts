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
    result = execute_intent(
        _intent(),
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        AuditLog(tmp_path / "a.jsonl"),
        TradingMode.live,
        False,
        queue,
    )
    assert result.status == "queued"
    assert broker.get_positions() == {}
    assert len(queue.list_pending()) == 1


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
