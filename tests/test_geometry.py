import json
from pathlib import Path

from cartonizer.geometry import geometry_validate
from cartonizer.solver import solve
from cartonizer.types import BoxType, Item, PackedBox, PackedItem


def test_volume_pass_but_3d_unfit_is_rejected():
    box = BoxType(id="A", inner_L=10, inner_W=10, inner_H=10)
    item = Item(id="sku1", L=6, W=6, H=6, weight=1.0, qty=4)
    packed = PackedBox(
        box_type_id="A",
        total_weight=4.0,
        items=[PackedItem(item_id="sku1", qty=4)],
    )

    result = geometry_validate(packed, box, {"sku1": item})

    assert not result.ok
    assert result.unfit_count > 0


def test_rotation_required_item_is_rejected_by_default():
    box = BoxType(id="A", inner_L=10, inner_W=5, inner_H=5)
    item = Item(id="sku1", L=5, W=10, H=5, weight=1.0, qty=1)
    packed = PackedBox(
        box_type_id="A",
        total_weight=1.0,
        items=[PackedItem(item_id="sku1", qty=1)],
    )

    result = geometry_validate(packed, box, {"sku1": item})

    assert not result.ok


def test_bm_case_original_overfilled_boxes_are_rejected():
    payload = json.loads(Path("examples/bm_case_01.json").read_text(encoding="utf-8"))
    items = {
        raw["id"]: Item(
            id=raw["id"],
            L=raw["L"],
            W=raw["W"],
            H=raw["H"],
            weight=raw["weight"],
            qty=raw["qty"],
        )
        for raw in payload["items"]
    }
    box_c_raw = next(raw for raw in payload["box_types"] if raw["id"] == "C")
    box_c = BoxType(
        id=box_c_raw["id"],
        inner_L=box_c_raw["inner_L"],
        inner_W=box_c_raw["inner_W"],
        inner_H=box_c_raw["inner_H"],
        max_weight=box_c_raw["max_weight"],
        min_weight=box_c_raw["min_weight"],
        tare_weight=box_c_raw["tare_weight"],
    )
    packed = PackedBox(
        box_type_id="C",
        total_weight=20.675,
        items=[PackedItem(item_id="X002FJN9IF", qty=110)],
    )

    result = geometry_validate(packed, box_c, items)

    assert not result.ok
    assert result.unfit_count > 0


def test_solver_expands_box_count_when_b_min_is_not_3d_feasible():
    box = BoxType(id="A", inner_L=10, inner_W=10, inner_H=10)
    items = [Item(id="sku1", L=5, W=5, H=5, weight=1.5, qty=24)]

    plan = solve(items, box, fill_rate=1.0, geometry_check=True)

    assert plan.status == "ok"
    assert len(plan.boxes) == 3
    assert all(geometry_validate(packed_box, box, {"sku1": items[0]}).ok for packed_box in plan.boxes)


def test_box_type_optimization_keeps_geometry_feasible_box():
    large = BoxType(id="L", inner_L=15, inner_W=10, inner_H=10)
    small = BoxType(id="S", inner_L=10, inner_W=10, inner_H=10)
    items = [Item(id="sku1", L=6, W=6, H=6, weight=6.0, qty=2)]

    plan = solve(items, [large, small], fill_rate=1.0, geometry_check=True)

    assert plan.status == "ok"
    assert len(plan.boxes) == 1
    assert plan.boxes[0].box_type_id == "L"
