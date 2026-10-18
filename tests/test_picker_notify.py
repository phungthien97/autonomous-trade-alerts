from app.picker.notify import build_failure_email_body, build_success_email_body
from app.picker.rank import SelectedSymbol


def test_success_email_contains_tickers_and_deltas() -> None:
    body = build_success_email_body(
        run_id="r1",
        as_of="2026-10-11",
        opt_window="2026-09-04..2026-09-10",
        score_window="2026-09-11..2026-10-11",
        selected=[
            SelectedSymbol("AAPL", 0.1, 0.2, 0.02, 0.03, 0.05),
            SelectedSymbol("MSFT", 0.05, 0.1, 0.01, 0.02, 0.04),
        ],
        active_symbols=["MSFT", "SMH"],
        skipped=[("BAD", "ConnectionError")],
        failure_pct=0.01,
        apply_after="2026-10-13T13:30:00+00:00",
    )
    assert "AAPL" in body and "MSFT" in body
    assert "Adds vs active: AAPL" in body
    assert "Drops vs active: SMH" in body
    assert "Monday open" in body


def test_failure_email_keep_previous() -> None:
    body = build_failure_email_body(
        run_id="r2",
        as_of="2026-10-11",
        skipped=[("X", "fail")],
        failure_pct=0.31,
        total_symbols=100,
    )
    assert "ABORT" in body
    assert "NOT overwritten" in body
