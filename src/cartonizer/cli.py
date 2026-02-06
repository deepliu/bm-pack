from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .solver import solve
from .types import BoxType, Item, PackingPlan


def _parse_input(payload: dict) -> tuple[list[BoxType], list[Item]]:
    items_data = payload.get("items")
    if not isinstance(items_data, list):
        raise ValueError("input missing 'items'")

    box_types_data = payload.get("box_types")
    if box_types_data is None:
        single = payload.get("box_type")
        if isinstance(single, dict):
            box_types_data = [single]
    if not isinstance(box_types_data, list):
        raise ValueError("input missing 'box_types' or 'box_type'")

    box_types: list[BoxType] = []
    for box_data in box_types_data:
        box_types.append(
            BoxType(
                id=str(box_data["id"]),
                inner_L=float(box_data["inner_L"]),
                inner_W=float(box_data["inner_W"]),
                inner_H=float(box_data["inner_H"]),
                max_weight=float(box_data.get("max_weight", 22.5)),
                min_weight=float(box_data.get("min_weight", 12.0)),
                tare_weight=float(box_data.get("tare_weight", 0.0)),
                cost=box_data.get("cost"),
            )
        )

    items: list[Item] = []
    for item in items_data:
        items.append(
            Item(
                id=str(item["id"]),
                L=float(item["L"]),
                W=float(item["W"]),
                H=float(item["H"]),
                weight=float(item["weight"]),
                qty=int(item["qty"]),
            )
        )
    return box_types, items


def _plan_to_dict(plan: PackingPlan) -> dict:
    return asdict(plan)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cartonizer CLI")
    parser.add_argument("--input", required=True, help="Path to input JSON")
    parser.add_argument(
        "--geometry-check",
        action="store_true",
        help="Run 3D geometry validation for each packed box",
    )
    parser.add_argument(
        "--geometry-viz-dir",
        help="Output directory for geometry visualization files",
    )
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    box_types, items = _parse_input(payload)
    plan = solve(
        items,
        box_types,
        geometry_check=args.geometry_check,
        geometry_visualize_dir=args.geometry_viz_dir,
    )
    print(json.dumps(_plan_to_dict(plan), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
