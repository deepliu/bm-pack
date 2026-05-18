from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cartonizer.solver import solve
from cartonizer.state import plan_quantities
from cartonizer.types import BoxType, Item, PackingPlan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "examples" / "erp_shipped_manual_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "output" / "erp_shipped_manual_comparison.json"


def _case_items(case: dict[str, Any]) -> list[Item]:
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


def _case_box_types(case: dict[str, Any]) -> list[BoxType]:
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


def _plan_payload(plan: PackingPlan, items: list[Item]) -> dict[str, Any]:
    item_map = {item.id: item for item in items}
    payload = asdict(plan)
    payload["quantity_summary"] = plan_quantities(plan) if plan.status == "ok" else {}
    payload["boxes"] = [
        {
            "box_no": index,
            "box_type_id": box.box_type_id,
            "total_weight": box.total_weight,
            "items": [
                {
                    "item_id": packed_item.item_id,
                    "qty": packed_item.qty,
                    "unit_weight": item_map[packed_item.item_id].weight,
                    "total_weight": item_map[packed_item.item_id].weight * packed_item.qty,
                }
                for packed_item in box.items
            ],
        }
        for index, box in enumerate(plan.boxes, start=1)
    ]
    return payload


def _manual_quantity_summary(case: dict[str, Any]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for box in case.get("manual_boxes") or []:
        for item in box.get("items") or []:
            key = str(item.get("goods_id") or item.get("sku") or "")
            if not key:
                continue
            summary[key] = summary.get(key, 0) + int(item.get("qty") or 0)
    return summary


def _compare_case(case: dict[str, Any]) -> dict[str, Any]:
    items = _case_items(case)
    box_types = _case_box_types(case)
    manual_box_count = len(case.get("manual_boxes") or [])
    strict_plan = solve(items, box_types, geometry_check=True, profile="strict")
    manual_like_plan = solve(items, box_types, geometry_check=True, profile="manual_like")
    manual_like_box_count = len(manual_like_plan.boxes) if manual_like_plan.status == "ok" else None
    strict_box_count = len(strict_plan.boxes) if strict_plan.status == "ok" else None
    return {
        "carton_plan_id": case["carton_plan_id"],
        "store_name": case["store_name"],
        "handle_date": case["handle_date"],
        "number": case["number"],
        "manual": {
            "box_count": manual_box_count,
            "quantity_summary": _manual_quantity_summary(case),
            "boxes": case.get("manual_boxes") or [],
        },
        "strict": {
            "status": strict_plan.status,
            "box_count": strict_box_count,
            "box_count_delta_vs_manual": (
                strict_box_count - manual_box_count
                if strict_box_count is not None
                else None
            ),
            "reason": strict_plan.reason,
            "plan": _plan_payload(strict_plan, items),
        },
        "manual_like": {
            "status": manual_like_plan.status,
            "box_count": manual_like_box_count,
            "box_count_delta_vs_manual": (
                manual_like_box_count - manual_box_count
                if manual_like_box_count is not None
                else None
            ),
            "reason": manual_like_plan.reason,
            "plan": _plan_payload(manual_like_plan, items),
        },
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    strict_ok = [row for row in results if row["strict"]["status"] == "ok"]
    manual_like_ok = [row for row in results if row["manual_like"]["status"] == "ok"]
    improved_feasibility = [
        row
        for row in results
        if row["strict"]["status"] != "ok" and row["manual_like"]["status"] == "ok"
    ]
    more_than_manual = [
        row
        for row in manual_like_ok
        if (row["manual_like"]["box_count_delta_vs_manual"] or 0) > 0
    ]
    same_or_less_than_manual = [
        row
        for row in manual_like_ok
        if (row["manual_like"]["box_count_delta_vs_manual"] or 0) <= 0
    ]
    return {
        "case_count": len(results),
        "strict_ok_count": len(strict_ok),
        "manual_like_ok_count": len(manual_like_ok),
        "improved_feasibility_count": len(improved_feasibility),
        "manual_like_same_or_less_than_manual_count": len(same_or_less_than_manual),
        "manual_like_more_than_manual_count": len(more_than_manual),
        "manual_like_infeasible": [
            {
                "carton_plan_id": row["carton_plan_id"],
                "reason": row["manual_like"]["reason"],
            }
            for row in results
            if row["manual_like"]["status"] != "ok"
        ],
        "manual_like_more_than_manual": [
            {
                "carton_plan_id": row["carton_plan_id"],
                "manual_box_count": row["manual"]["box_count"],
                "manual_like_box_count": row["manual_like"]["box_count"],
                "delta": row["manual_like"]["box_count_delta_vs_manual"],
            }
            for row in more_than_manual
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare bm-pack strict/manual_like plans with exported ERP manual carton plans."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    results = [_compare_case(case) for case in payload.get("cases") or []]
    report = {
        "input": str(input_path),
        "summary": _summary(results),
        "cases": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"written comparison report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
