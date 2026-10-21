from app.picker.sizing import (
    allocate_priority_sleeves,
    sleeve_buy_budget,
    whole_share_allocation,
)


def test_sleeve_buy_budget_splits_remaining() -> None:
    assert sleeve_buy_budget(900.0, n_active_non_exit_only=3, n_already_long=1) == 450.0
    assert sleeve_buy_budget(1000.0, n_active_non_exit_only=1, n_already_long=0) == 1000.0
    assert sleeve_buy_budget(0.0, n_active_non_exit_only=3, n_already_long=0) == 0.0


def test_whole_share_allocation_stretches_above_even_split() -> None:
    # Even split $600 but share is $800 — stretch to 1 share from the pool.
    assert whole_share_allocation(price=800.0, slot_target=600.0, remaining_cash=3000.0) == (
        1,
        800.0,
    )


def test_whole_share_allocation_fills_closest_to_target() -> None:
    # $127 stock, $600 target → 4 shares = $508
    assert whole_share_allocation(price=127.0, slot_target=600.0, remaining_cash=3000.0) == (
        4,
        508.0,
    )


def test_whole_share_allocation_skips_when_unaffordable() -> None:
    assert whole_share_allocation(price=900.0, slot_target=600.0, remaining_cash=500.0) is None


def test_allocate_priority_sleeves_funds_expensive_top_names() -> None:
    ranked = ["P", "FICO", "HUM", "AMGN", "VLO", "CHEAP"]
    prices = {
        "P": 800.0,
        "FICO": 800.0,
        "HUM": 428.0,
        "AMGN": 439.0,
        "VLO": 434.0,
        "CHEAP": 50.0,
    }
    out = allocate_priority_sleeves(ranked, prices, 3000.0, max_n=5)
    assert [a.symbol for a in out] == ["P", "FICO", "HUM", "AMGN", "VLO"]
    assert out[0].cash >= 800.0  # stretch + leftover park
    assert out[1].cash >= 800.0
    assert abs(sum(a.cash for a in out) - 3000.0) < 0.02


def test_allocate_priority_sleeves_parks_leftover_so_book_sums() -> None:
    ranked = ["A", "B"]
    prices = {"A": 100.0, "B": 100.0}
    out = allocate_priority_sleeves(ranked, prices, 250.0, max_n=2)
    assert abs(sum(a.cash for a in out) - 250.0) < 0.02
    assert all(a.shares >= 1 for a in out)


def test_allocate_priority_sleeves_walks_list_when_tail_unaffordable() -> None:
    ranked = ["EXPENSIVE", "A", "B", "C", "D", "E"]
    prices = {
        "EXPENSIVE": 5000.0,  # skip — cannot buy
        "A": 100.0,
        "B": 100.0,
        "C": 100.0,
        "D": 100.0,
        "E": 100.0,
    }
    out = allocate_priority_sleeves(ranked, prices, 1000.0, max_n=5)
    assert [a.symbol for a in out] == ["A", "B", "C", "D", "E"]
    assert all(a.shares >= 1 for a in out)


def test_allocate_priority_sleeves_may_return_fewer_than_max() -> None:
    ranked = ["A", "B"]
    prices = {"A": 400.0, "B": 400.0}
    out = allocate_priority_sleeves(ranked, prices, 500.0, max_n=5)
    assert [a.symbol for a in out] == ["A"]
    # Only A fits; leftover $100 parks on that sleeve so book still sums to $500.
    assert abs(out[0].cash - 500.0) < 0.02
    assert out[0].shares == 1
