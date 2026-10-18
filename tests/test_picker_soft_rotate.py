from app.picker.soft_rotate import plan_soft_rotate


def test_plan_soft_rotate_add_drop_keep() -> None:
    plan = plan_soft_rotate(["A", "B", "C"], ["B", "C", "D"])
    assert plan.kept == ["B", "C"]
    assert plan.added == ["D"]
    assert plan.dropped == ["A"]
    assert plan.flags["A"].exit_only is True
    assert plan.flags["D"].awaiting_first_buy is True
    assert plan.flags["B"].exit_only is False
    assert plan.flags["B"].awaiting_first_buy is False


def test_plan_soft_rotate_empty_pending_exits_all() -> None:
    plan = plan_soft_rotate(["A", "B"], [])
    assert plan.added == []
    assert plan.kept == []
    assert plan.dropped == ["A", "B"]
    assert plan.flags["A"].exit_only is True
    assert plan.flags["B"].exit_only is True
