from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

# if __package__ is None or __package__ == "":
#     sys.path.append(str(Path(__file__).resolve().parents[1]))

from cartonizer.solver import solve
from cartonizer.types import BoxType, Item


def _load_payload(path: Path) -> tuple[list[BoxType], list[Item]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def run_batch(
    inputs: Iterable[Path],
    *,
    plan_dir: Path,
    viz_dir: Optional[Path] = None,
    geometry_check: bool = False,
) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    if viz_dir is not None:
        viz_dir.mkdir(parents=True, exist_ok=True)

    for input_path in inputs:
        box_types, items = _load_payload(input_path)
        plan = solve(
            items,
            box_types,
            geometry_check=geometry_check,
            geometry_visualize_dir=str(viz_dir) if viz_dir else None,
        )
        output_path = plan_dir / f"{input_path.stem}_plan.json"
        output_path.write_text(
            json.dumps(asdict(plan), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    # 在 PyCharm 里直接运行这个文件，支持断点调试。
    # 只需要改下面这些变量即可，不走 CLI。
    # inputs = sorted(Path("examples").glob("bm_case_*.json"))
    # inputs = sorted(Path("examples").glob("bm_data.json"))
    # inputs = sorted(Path("examples").glob("bm_case_factory.json"))
    # inputs = sorted(Path("examples").glob("bm_case_goods_list.json"))
    # inputs = sorted(Path("examples").glob("bm_case_goods_list_1.json"))
    inputs = sorted(Path("examples").glob("bm_case_goods_list_3.json"))

    print(inputs)
    run_batch(
        inputs,
        plan_dir=Path("output/plans"),
        viz_dir=Path("output/viz"),
        geometry_check=True,
    )
