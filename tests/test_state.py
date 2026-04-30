from cartonizer.repair import BoxState
from cartonizer.state import (
    MutableBox,
    box_state_to_packed_box,
    expand_items,
    item_fits_box,
    item_volume,
    order_item_weight,
    plan_quantities,
)
from cartonizer.types import BoxType, Item, PackingPlan


def test_state_weight_volume_and_tare_are_explicit():
    box_type = BoxType(
        id="A",
        inner_L=100,
        inner_W=100,
        inner_H=100,
        tare_weight=0.5,
    )
    item = Item(id="sku1", L=10, W=20, H=30, weight=2.0, qty=3)
    mutable = MutableBox(
        box_type=box_type,
        items={"sku1": 3},
        items_weight=item.weight * item.qty,
        items_volume=item_volume(item) * item.qty,
    )

    packed = mutable.to_packed_box()

    assert packed.total_weight == 6.5
    assert mutable.items_weight == 6.0
    assert mutable.tare_weight == 0.5
    assert mutable.items_volume == 18000


def test_box_state_to_public_plan_preserves_quantities():
    box_state = BoxState(
        box_type_id="A",
        min_weight=12.0,
        max_weight=22.5,
        tare_weight=0.5,
        box_volume=1000.0,
        max_volume=900.0,
        total_weight=12.5,
        total_volume=400.0,
        items={"sku1": 2, "sku2": 3},
    )
    packed = box_state_to_packed_box(box_state)
    plan = PackingPlan(status="ok", reason="", boxes=[packed], metrics={})

    assert packed.total_weight == 12.5
    assert plan_quantities(plan) == {"sku1": 2, "sku2": 3}


def test_item_helpers_are_stable():
    items = [
        Item(id="sku1", L=1, W=2, H=3, weight=4.0, qty=2),
        Item(id="sku2", L=10, W=10, H=10, weight=1.5, qty=0),
    ]
    box_type = BoxType(id="A", inner_L=2, inner_W=3, inner_H=4)

    assert order_item_weight(items) == 8.0
    assert len(expand_items(items)) == 2
    assert item_fits_box(items[0], box_type)
    assert not item_fits_box(Item(id="too-large", L=3, W=3, H=3, weight=1, qty=1), box_type)
