from cartonizer.solver import pack_order
from cartonizer.types import BoxType, Item


def test_repair_underweight_boxes_into_range():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100)
    items = [Item(id="sku1", L=1, W=1, H=1, weight=5.0, qty=6)]
    plan = pack_order(items, box)
    assert plan.status == "ok"
    assert len(plan.boxes) == 2
    for packed_box in plan.boxes:
        assert box.min_weight <= packed_box.total_weight <= box.max_weight


def test_repair_does_not_create_overweight():
    box = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100)
    items = [Item(id="sku1", L=1, W=1, H=1, weight=5.0, qty=6)]
    plan = pack_order(items, box)
    assert plan.status == "ok"
    assert all(packed_box.total_weight <= box.max_weight for packed_box in plan.boxes)
