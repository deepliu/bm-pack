from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .solver import pack_order
from .types import BoxType, Item, PackingPlan


def _parse_input(payload: dict) -> tuple[BoxType, list[Item]]:
    box_data = payload.get("box_type")
    if not isinstance(box_data, dict):
        raise ValueError("input missing 'box_type'")
    items_data = payload.get("items")
    if not isinstance(items_data, list):
        raise ValueError("input missing 'items'")

    box = BoxType(
        id=str(box_data["id"]),
        inner_L=float(box_data["inner_L"]),
        inner_W=float(box_data["inner_W"]),
        inner_H=float(box_data["inner_H"]),
        max_weight=float(box_data.get("max_weight", 22.5)),
        min_weight=float(box_data.get("min_weight", 12.0)),
        tare_weight=float(box_data.get("tare_weight", 0.0)),
        cost=box_data.get("cost"),
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
    return box, items


def _plan_to_dict(plan: PackingPlan) -> dict:
    return asdict(plan)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cartonizer CLI")
    parser.add_argument("--input", required=True, help="Path to input JSON")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    box, items = _parse_input(payload)
    plan = pack_order(items, box)
    print(json.dumps(_plan_to_dict(plan), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
