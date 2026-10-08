from app.broker import InMemoryBroker
from app.live.reconcile import LocalSleeveState, reconcile


def test_detects_share_drift() -> None:
    broker = InMemoryBroker(cash_usd=500.0, positions={"AAPL": 2.0}, last_prices={"AAPL": 100.0})
    local = LocalSleeveState(cash=400.0, shares={"AAPL": 1.0})
    report = reconcile(local, broker)
    assert len(report.drifts) == 1
    assert report.drifts[0].local_shares == 1.0
    assert report.drifts[0].broker_shares == 2.0
    assert report.corrected.shares["AAPL"] == 2.0
    assert report.corrected.cash == 500.0


def test_no_drift() -> None:
    broker = InMemoryBroker(cash_usd=800.0, positions={"MSFT": 1.0}, last_prices={"MSFT": 200.0})
    local = LocalSleeveState(cash=800.0, shares={"MSFT": 1.0})
    report = reconcile(local, broker)
    assert report.drifts == []
    assert report.corrected.shares == {"MSFT": 1.0}
