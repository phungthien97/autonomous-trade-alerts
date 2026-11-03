from app.picker.hard_rotate import plan_hard_rotate


def test_plan_hard_rotate_kept_also_awaits_rebuy() -> None:
    plan = plan_hard_rotate(["A", "B", "C"], ["B", "C", "D"])
    assert plan.kept == ["B", "C"]
    assert plan.added == ["D"]
    assert plan.dropped == ["A"]
    assert plan.target == ["B", "C", "D"]
    # Kept names are sold in flatten, then re-entered — awaiting stays True.
    assert plan.flags["B"].awaiting_first_buy is True
    assert plan.flags["B"].exit_only is False
    assert plan.flags["D"].awaiting_first_buy is True
    assert plan.flags["A"].exit_only is True
    assert plan.flags["A"].awaiting_first_buy is False


def test_plan_hard_rotate_empty_pending_exits_all() -> None:
    plan = plan_hard_rotate(["A", "B"], [])
    assert plan.target == []
    assert plan.dropped == ["A", "B"]
    assert plan.flags["A"].exit_only is True
