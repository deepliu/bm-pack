import json
from pathlib import Path

from cartonizer.solver import solve
from cartonizer.state import plan_quantities
from cartonizer.types import BoxType, Item


def _case_items(case):
    return [
        Item(
            id=str(raw["item_id"]),
            L=float(raw["length"]),
            W=float(raw["width"]),
            H=float(raw["height"]),
            weight=float(raw["weight"]),
            qty=int(raw["qty"]),
        )
        for raw in case["items"]
    ]


def _case_box_types(case):
    return [
        BoxType(
            id=str(raw["id"]),
            inner_L=float(raw["inner_L"]),
            inner_W=float(raw["inner_W"]),
            inner_H=float(raw["inner_H"]),
            max_weight=float(raw["max_weight"]),
            min_weight=float(raw["min_weight"]),
            tare_weight=float(raw.get("tare_weight") or 0),
        )
        for raw in case["box_types"]
    ]


def test_erp_shipped_manual_cases_are_exported_and_solvable_baseline():
    payload = json.loads(
        Path("examples/erp_shipped_manual_cases.json").read_text(encoding="utf-8")
    )
    cases = payload.get("cases") or []
    filters = payload.get("filters") or {}

    assert len(cases) >= 10
    assert filters.get("min_manual_box_weight") == 12.0
    assert filters.get("max_manual_box_sku_types") == 6
    assert filters.get("min_manual_box_count") == 2
    ok_count = 0
    infeasible = []
    for case in cases:
        assert case["carton_plan_id"]
        assert case["box_types"]
        assert case["items"]
        assert case["manual_boxes"]
        assert case["manual_metrics"]["box_count"] == len(case["manual_boxes"])
        assert len(case["manual_boxes"]) >= 2
        for manual_box in case["manual_boxes"]:
            assert float(manual_box["total_weight"]) >= 12.0
            assert len(manual_box["items"]) <= 6

        items = _case_items(case)
        box_types = _case_box_types(case)
        box_types_by_id = {box_type.id: box_type for box_type in box_types}
        plan = solve(items, box_types, geometry_check=True, profile="manual_like")
        if plan.status != "ok":
            infeasible.append((case["carton_plan_id"], plan.reason))
            continue

        ok_count += 1
        assert plan_quantities(plan) == {item.id: item.qty for item in items}
        for packed_box in plan.boxes:
            assert packed_box.total_weight <= box_types_by_id[packed_box.box_type_id].max_weight
            assert len(packed_box.items) <= 6

    assert ok_count >= max(1, len(cases) - 2), infeasible


def test_strict_can_split_whole_sku_groups_without_geometry_hard_check():
    items = [
        Item(id="43", L=100, W=40, H=50, weight=0.104, qty=25),
        Item(id="32", L=47, W=18, H=70, weight=0.0125, qty=30),
        Item(id="72", L=47, W=18, H=70, weight=0.0271, qty=20),
        Item(id="127", L=100, W=40, H=50, weight=0.213, qty=40),
        Item(id="52", L=100, W=40, H=50, weight=0.1388, qty=20),
        Item(id="89", L=70, W=46, H=50, weight=0.06, qty=20),
        Item(id="180", L=100, W=80, H=50, weight=0.114, qty=15),
        Item(id="16", L=100, W=40, H=50, weight=0.105, qty=25),
        Item(id="56", L=100, W=40, H=50, weight=0.1021, qty=20),
    ]
    box_types = [
        BoxType(id="A", inner_L=520, inner_W=330, inner_H=300, max_weight=22, min_weight=11.5, tare_weight=0.85),
        BoxType(id="C", inner_L=420, inner_W=280, inner_H=230, max_weight=22, min_weight=11.5, tare_weight=0.6),
    ]
    box_types_by_id = {box_type.id: box_type for box_type in box_types}

    plan = solve(items, box_types, geometry_check=False)

    assert plan.status == "ok"
    assert len(plan.boxes) == 2
    assert plan_quantities(plan) == {item.id: item.qty for item in items}
    for packed_box in plan.boxes:
        box_type = box_types_by_id[packed_box.box_type_id]
        assert box_type.min_weight <= packed_box.total_weight <= box_type.max_weight
        assert len(packed_box.items) <= 6


def test_case_89_keeps_manual_box_count_with_no_more_than_three_skus_per_box():
    payload = json.loads(
        Path("examples/erp_shipped_manual_cases.json").read_text(encoding="utf-8")
    )
    case = next(row for row in payload["cases"] if row["carton_plan_id"] == 89)
    items = _case_items(case)
    box_types = _case_box_types(case)
    box_types_by_id = {box_type.id: box_type for box_type in box_types}

    plan = solve(items, box_types, geometry_check=False)

    assert plan.status == "ok"
    assert len(plan.boxes) == len(case["manual_boxes"])
    assert plan_quantities(plan) == {item.id: item.qty for item in items}
    assert max(len(packed_box.items) for packed_box in plan.boxes) <= 3
    for packed_box in plan.boxes:
        box_type = box_types_by_id[packed_box.box_type_id]
        assert box_type.min_weight <= packed_box.total_weight <= box_type.max_weight
