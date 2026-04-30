from cartonizer.geometry_engine import GeometryEngine
from cartonizer.optimizers import optimize_box_types, optimize_quantities
from cartonizer.types import BoxType, Item, PackedBox, PackedItem, PackingPlan


def test_optimize_box_types_does_not_choose_geometry_bad_smaller_box():
    large = BoxType(id="L", inner_L=15, inner_W=10, inner_H=10)
    small = BoxType(id="S", inner_L=10, inner_W=10, inner_H=10)
    item = Item(id="sku1", L=6, W=6, H=6, weight=6.0, qty=2)
    plan = PackingPlan(
        status="ok",
        reason="",
        boxes=[
            PackedBox(
                box_type_id="L",
                total_weight=12.0,
                items=[PackedItem(item_id="sku1", qty=2)],
            )
        ],
        metrics={"fill_rate": 1.0},
    )

    optimized = optimize_box_types(
        plan,
        items_by_id={"sku1": item},
        box_types=[small, large],
        geometry_engine=GeometryEngine(items_by_id={"sku1": item}, enabled=True),
        fill_rate=1.0,
    )

    assert optimized.boxes[0].box_type_id == "L"


def test_optimize_quantities_preserves_quantities_and_weight_range():
    box_type = BoxType(id="A", inner_L=100, inner_W=100, inner_H=100)
    item = Item(id="sku1", L=1, W=1, H=1, weight=1.0, qty=25)
    plan = PackingPlan(
        status="ok",
        reason="",
        boxes=[
            PackedBox(
                box_type_id="A",
                total_weight=13.0,
                items=[PackedItem(item_id="sku1", qty=13)],
            ),
            PackedBox(
                box_type_id="A",
                total_weight=12.0,
                items=[PackedItem(item_id="sku1", qty=12)],
            ),
        ],
        metrics={"fill_rate": 1.0},
    )

    optimized = optimize_quantities(
        plan,
        items_by_id={"sku1": item},
        box_types_by_id={"A": box_type},
        geometry_engine=GeometryEngine(items_by_id={"sku1": item}, enabled=True),
        fill_rate=1.0,
    )

    assert sum(pi.qty for box in optimized.boxes for pi in box.items) == 25
    assert all(box_type.min_weight <= box.total_weight <= box_type.max_weight for box in optimized.boxes)
