from app.picker.sizing import resolve_equal_buy_cash_cap

assert resolve_equal_buy_cash_cap(
    3000, n_active_non_exit_only=5, n_already_long=0, price=800
) == 800
assert resolve_equal_buy_cash_cap(
    1000, n_active_non_exit_only=5, n_already_long=0, price=100
) == 200
print("ovh-ok")
