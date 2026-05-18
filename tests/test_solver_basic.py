from cartonizer.solver import solve
from cartonizer.types import BoxType, Item


def test_boxes_within_weight_range():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100)
    items = [Item(id="sku1", L=1, W=1, H=1, weight=7.5, qty=6)]
    plan = solve(items, box)
    assert plan.status == "ok"
    assert all(
        box.min_weight <= packed_box.total_weight <= box.max_weight
        for packed_box in plan.boxes
    )


def test_stage_a_no_overweight():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100)
    items = [Item(id="sku1", L=1, W=1, H=1, weight=6.0, qty=7)]
    plan = solve(items, box)
    assert plan.status == "ok"
    assert all(packed_box.total_weight <= box.max_weight for packed_box in plan.boxes)


def test_keep_single_sku_together_when_possible():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100)
    items = [
        Item(id="sku1", L=1, W=1, H=1, weight=6.0, qty=3),
        Item(id="sku2", L=1, W=1, H=1, weight=6.0, qty=3),
    ]
    plan = solve(items, box)
    assert plan.status == "ok"
    assert all(len(packed_box.items) == 1 for packed_box in plan.boxes)


def test_stage_a_oversize_item_infeasible():
    box = BoxType(id="A", inner_L=10, inner_W=10, inner_H=10)
    items = [Item(id="sku1", L=11, W=9, H=9, weight=1.0, qty=1)]
    plan = solve(items, box)
    assert plan.status == "infeasible"


def test_manual_like_profile_allows_light_single_box():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100, min_weight=12.0)
    items = [Item(id="sku1", L=10, W=10, H=10, weight=0.5, qty=1)]

    strict_plan = solve(items, box)
    manual_like_plan = solve(items, box, profile="manual_like")

    assert strict_plan.status == "infeasible"
    assert manual_like_plan.status == "ok"
    assert len(manual_like_plan.boxes) == 1
    assert manual_like_plan.metrics["underweight_boxes"] == 1.0


def test_manual_like_profile_still_rejects_overweight_box():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100, max_weight=3.0)
    items = [Item(id="sku1", L=10, W=10, H=10, weight=2.0, qty=3)]

    plan = solve(items, box, profile="manual_like")

    assert plan.status == "ok"
    assert all(packed_box.total_weight <= box.max_weight for packed_box in plan.boxes)


def test_solver_never_relaxes_single_box_sku_types_above_six():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100, min_weight=0.0, max_weight=100.0)
    items = [
        Item(id=f"sku{i}", L=1, W=1, H=1, weight=1.0, qty=1)
        for i in range(7)
    ]

    plan = solve(items, box, profile="manual_like", max_sku_types=3)

    assert plan.status == "ok"
    assert max(len(packed_box.items) for packed_box in plan.boxes) <= 6
    assert plan.metrics["max_sku_types_cap"] == 6.0
