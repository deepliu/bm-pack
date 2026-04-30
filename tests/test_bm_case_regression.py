import json
from pathlib import Path

from cartonizer.geometry_engine import GeometryEngine
from cartonizer.solver import solve
from cartonizer.state import plan_quantities
from cartonizer.types import BoxType, Item


def _load_bm_case_01() -> tuple[list[BoxType], list[Item]]:
    payload = json.loads(Path("examples/bm_case_01.json").read_text(encoding="utf-8"))
    box_types = [
        BoxType(
            id=str(raw["id"]),
            inner_L=float(raw["inner_L"]),
            inner_W=float(raw["inner_W"]),
            inner_H=float(raw["inner_H"]),
            max_weight=float(raw.get("max_weight", 22.5)),
            min_weight=float(raw.get("min_weight", 12.0)),
            tare_weight=float(raw.get("tare_weight", 0.0)),
        )
        for raw in payload["box_types"]
    ]
    items = [
        Item(
            id=str(raw["id"]),
            L=float(raw["L"]),
            W=float(raw["W"]),
            H=float(raw["H"]),
            weight=float(raw["weight"]),
            qty=int(raw["qty"]),
        )
        for raw in payload["items"]
    ]
    return box_types, items


def test_bm_case_01_geometry_checked_solution_is_real_packable():
    box_types, items = _load_bm_case_01()
    box_types_by_id = {box_type.id: box_type for box_type in box_types}
    items_by_id = {item.id: item for item in items}
    engine = GeometryEngine(items_by_id=items_by_id, enabled=True)

    plan = solve(items, box_types, geometry_check=True)

    assert plan.status == "ok"
    assert plan_quantities(plan) == {item.id: item.qty for item in items}
    for packed_box in plan.boxes:
        box_type = box_types_by_id[packed_box.box_type_id]
        assert box_type.min_weight <= packed_box.total_weight <= box_type.max_weight
        assert engine.validate_box(packed_box, box_type).ok
