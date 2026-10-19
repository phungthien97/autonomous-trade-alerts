from app.picker.notify import (
    build_failure_email_body,
    build_success_email_body,
    build_success_email_subject,
)
from app.picker.rank import SelectedSymbol
from app.picker.sp500 import Sp500Constituent


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
        profiles={
            "AAPL": Sp500Constituent("AAPL", "Apple Inc.", "Information Technology"),
            "MSFT": Sp500Constituent("MSFT", "Microsoft", "Information Technology"),
        },
    )
    assert "AAPL" in body and "MSFT" in body
    assert "Apple Inc. · Information Technology" in body
    assert "Microsoft · Information Technology" in body
    assert "Adding:   AAPL" in body
    assert "Dropping: SMH" in body
    assert "Keeping:  MSFT" in body
    assert "Monday open" in body
    assert "strategy +20.0%" in body
    assert "beat B&H by +10.0%" in body
    assert "What happens next" in body
    assert "edge=" not in body  # no raw jargon decimals


def test_success_email_subject_lists_symbols() -> None:
    selected = [
        SelectedSymbol("P", 0.05, 0.28, 0.02, 0.03, 0.1),
        SelectedSymbol("FICO", 0.04, 0.2, 0.02, 0.03, 0.1),
    ]
    assert build_success_email_subject(selected) == "[PICKER] Mon apply: P, FICO"
    assert "DRY RUN" in build_success_email_subject(selected, dry_run=True)


def test_failure_email_keep_previous() -> None:
    body = build_failure_email_body(
        run_id="r2",
        as_of="2026-10-11",
        skipped=[("X", "fail")],
        failure_pct=0.31,
        total_symbols=100,
    )
    assert "FAILED" in body
    assert "NOT overwritten" in body
    assert "What this means" in body
