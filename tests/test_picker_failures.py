from app.picker.failures import evaluate_fetch_failures


def test_evaluate_fetch_failures_boundaries() -> None:
    assert evaluate_fetch_failures(100, 0).abort is False
    assert evaluate_fetch_failures(100, 29).abort is False
    assert evaluate_fetch_failures(100, 30).abort is False  # exact 30% proceeds
    assert evaluate_fetch_failures(100, 31).abort is True


def test_evaluate_fetch_failures_zero_total_aborts() -> None:
    result = evaluate_fetch_failures(0, 0)
    assert result.abort is True
    assert result.failure_pct == 1.0
