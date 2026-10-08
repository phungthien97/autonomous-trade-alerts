from __future__ import annotations

from dataclasses import dataclass, field

from app.broker.base import BrokerClient


@dataclass
class LocalSleeveState:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)


@dataclass
class Drift:
    symbol: str
    local_shares: float
    broker_shares: float


@dataclass
class ReconcileReport:
    broker_cash: float
    broker_positions: dict[str, float]
    drifts: list[Drift]
    corrected: LocalSleeveState


def reconcile(local_state: LocalSleeveState, broker: BrokerClient) -> ReconcileReport:
    snapshot = broker.get_account_snapshot()
    positions = broker.get_positions()
    symbols = set(local_state.shares) | set(positions)
    drifts: list[Drift] = []
    for symbol in sorted(symbols):
        local_qty = float(local_state.shares.get(symbol, 0.0))
        broker_qty = float(positions.get(symbol, 0.0))
        if abs(local_qty - broker_qty) > 1e-9:
            drifts.append(Drift(symbol, local_qty, broker_qty))
    corrected = LocalSleeveState(cash=snapshot.cash_usd, shares=dict(positions))
    return ReconcileReport(
        broker_cash=snapshot.cash_usd,
        broker_positions=dict(positions),
        drifts=drifts,
        corrected=corrected,
    )
