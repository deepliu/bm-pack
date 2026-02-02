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
