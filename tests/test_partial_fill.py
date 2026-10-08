from app.audit import AuditLog
from app.broker import InMemoryBroker
from app.live.executor import execute_intent
from app.live.idempotency import IdempotencyStore
from app.live.modes import TradingMode
from app.live.planner import OrderIntent
from app.live.queue import PendingIntentStore


def test_partial_fill_cancels_rest_and_keeps_filled_only(tmp_path) -> None:
    broker = InMemoryBroker(1000.0, last_prices={"AAPL": 10.0}, partial_fill_ratio=0.5)
    audit = AuditLog(tmp_path / "audit.jsonl")
    result = execute_intent(
        OrderIntent("AAPL", "BUY", 4.0, 0.4, "bar-1", "test"),
        broker,
        IdempotencyStore(tmp_path / "id.json"),
        audit,
        TradingMode.broker_paper,
        True,
        PendingIntentStore(tmp_path / "q.json"),
    )
    assert result.status == "partial"
    assert broker.get_positions()["AAPL"] == 2.0
    assert broker.cancelled == ["mem-1"]
    events = [row["event_type"] for row in audit.read_all()]
    assert "partial" in events
    assert "cancel" in events
