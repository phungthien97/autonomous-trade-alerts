from __future__ import annotations

from dataclasses import dataclass

from app.audit.log import AuditLog
from app.broker.base import BrokerClient
from app.live.idempotency import IdempotencyStore, intent_key
from app.live.modes import TradingMode
from app.live.planner import OrderIntent
from app.live.queue import PendingIntent, PendingIntentStore


@dataclass
class ExecuteResult:
    status: str
    order_id: str | None = None


def execute_intent(
    intent: OrderIntent,
    broker: BrokerClient,
    idempotency: IdempotencyStore,
    audit: AuditLog,
    mode: TradingMode,
    rth_ok: bool,
    queue: PendingIntentStore,
) -> ExecuteResult:
    key = intent_key(intent.symbol, intent.bar_ts, intent.side)
    if idempotency.already_done(key):
        audit.append("skipped", {"key": key})
        return ExecuteResult("skipped")
    if not rth_ok:
        queue.enqueue(
            PendingIntent(
                symbol=intent.symbol,
                side=intent.side,
                bar_ts=intent.bar_ts,
                created_at=intent.bar_ts,
                reason=intent.reason,
            )
        )
        audit.append("queued", {"symbol": intent.symbol, "side": intent.side, "bar_ts": intent.bar_ts})
        return ExecuteResult("queued")
    if mode in (TradingMode.sim, TradingMode.live_dry_run):
        audit.append("dry_run", {"symbol": intent.symbol, "side": intent.side, "quantity": intent.quantity})
        idempotency.mark_done(key, {"status": "dry_run"})
        return ExecuteResult("dry_run")
    if mode not in (TradingMode.broker_paper, TradingMode.live):
        return ExecuteResult("skipped")
    result = broker.place_market_order(intent.symbol, intent.side, intent.quantity)
    audit.append("order_submitted", {"order_id": result.order_id, "status": result.status})
    if result.status == "partial":
        audit.append(
            "partial",
            {"order_id": result.order_id, "filled_qty": result.filled_qty, "remaining_qty": result.remaining_qty},
        )
        if result.remaining_qty > 0:
            broker.cancel_order(result.order_id)
            audit.append("cancel", {"order_id": result.order_id})
    elif result.status == "filled":
        audit.append("fill", {"order_id": result.order_id, "filled_qty": result.filled_qty, "avg_price": result.avg_price})
    idempotency.mark_done(key, {"order_id": result.order_id, "status": result.status})
    return ExecuteResult(result.status, result.order_id)
