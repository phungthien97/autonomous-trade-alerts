from app.picker.sizing import sleeve_buy_budget


def test_sleeve_buy_budget_splits_remaining() -> None:
    assert sleeve_buy_budget(900.0, n_active_non_exit_only=3, n_already_long=1) == 450.0
    assert sleeve_buy_budget(1000.0, n_active_non_exit_only=1, n_already_long=0) == 1000.0
    assert sleeve_buy_budget(0.0, n_active_non_exit_only=3, n_already_long=0) == 0.0
