import os

from app.account_snapshot import AccountSnapshot
from app.remote.marks import DASHBOARD_IB_CLIENT_ID_DEFAULT, dashboard_ib_client_id, overlay_ibkr_marks


def test_dashboard_ib_client_id_default(monkeypatch) -> None:
    monkeypatch.delenv("DASHBOARD_IB_CLIENT_ID", raising=False)
    assert dashboard_ib_client_id() == DASHBOARD_IB_CLIENT_ID_DEFAULT
    assert DASHBOARD_IB_CLIENT_ID_DEFAULT == 9


def test_dashboard_ib_client_id_env(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_IB_CLIENT_ID", "11")
    assert dashboard_ib_client_id() == 11


class _FakeBroker:
    def __init__(self) -> None:
        self.last_prices = {"AAPL": 101.0}
        self.ib = type("IB", (), {"disconnect": lambda self: None})()

    def get_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            900.0,
            900.0,
            1000.0,
            available_funds_usd=900.0,
            gross_position_value_usd=100.0,
            accrued_cash_usd=0.0,
        )

    def get_positions(self) -> dict[str, float]:
        return {"AAPL": 2.0}


def test_overlay_ibkr_marks_success(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_IB_CLIENT_ID", "9")
    base = {
        "cash_usd": 1000.0,
        "positions": [{"symbol": "AAPL", "shares": 1.0, "cash": 0.0, "last_price": 99.0, "peak": None, "trough": None}],
    }
    out = overlay_ibkr_marks(base, broker_factory=_FakeBroker)
    assert out["marks_source"] == "ibkr"
    assert out["cash_usd"] == 900.0
    assert out["broker_equity_usd"] == 1000.0
    assert out["gross_position_value_usd"] == 100.0
    assert out["accrued_cash_usd"] == 0.0
    assert out["available_funds_usd"] == 900.0
    assert out["spendable_usd"] == 900.0  # long but AF == cash
    assert out["positions"][0]["shares"] == 2.0
    assert out["positions"][0]["last_price"] == 101.0
    assert os.environ.get("IB_CLIENT_ID") == "9"


def test_overlay_ibkr_marks_fallback_on_error() -> None:
    def boom():
        raise ConnectionError("gateway down")

    base = {"cash_usd": 1000.0, "positions": []}
    out = overlay_ibkr_marks(base, broker_factory=boom)
    assert out["marks_source"] == "files"
    assert out["cash_usd"] == 1000.0
    assert "marks_error" in out


def test_overlay_without_factory_keeps_files() -> None:
    base = {"cash_usd": 1.0, "positions": []}
    out = overlay_ibkr_marks(base)
    assert out["marks_source"] == "files"
