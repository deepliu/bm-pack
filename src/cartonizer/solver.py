from __future__ import annotations

from math import ceil
from typing import Iterable

from .feasibility import check_feasibility
from .repair import BoxState, repair_underweight
from .types import BoxType, Item, PackedBox, PackedItem, PackingPlan


def _volume(item: Item) -> float:
    return item.L * item.W * item.H


def _fits_with_rotation(item: Item, box: BoxType, allow_rotate: bool) -> bool:
    dims = (item.L, item.W, item.H)
    box_dims = (box.inner_L, box.inner_W, box.inner_H)
    if not allow_rotate:
        return all(d <= b for d, b in zip(dims, box_dims))
    perms = (
        (dims[0], dims[1], dims[2]),
        (dims[0], dims[2], dims[1]),
        (dims[1], dims[0], dims[2]),
        (dims[1], dims[2], dims[0]),
        (dims[2], dims[0], dims[1]),
        (dims[2], dims[1], dims[0]),
    )
    return any(all(d <= b for d, b in zip(p, box_dims)) for p in perms)


def _expand_items(items: Iterable[Item]) -> list[Item]:
    expanded: list[Item] = []
    for item in items:
        if item.qty <= 0:
            continue
        expanded.extend(
            Item(
                id=item.id,
                L=item.L,
                W=item.W,
                H=item.H,
                weight=item.weight,
                qty=1,
            )
            for _ in range(item.qty)
        )
    return expanded


def pack_order(
    items: list[Item],
    box_type: BoxType,
    *,
    allow_rotate: bool = True,
    fill_rate: float = 0.90,
) -> PackingPlan:
    feasibility = check_feasibility(items, box_type)
    total_weight = feasibility.total_weight
    if not feasibility.ok:
        return PackingPlan(
            status="infeasible",
            reason=feasibility.reason,
            boxes=[],
            metrics={
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
            },
        )

    if fill_rate <= 0:
        return PackingPlan(
            status="infeasible",
            reason="infeasible: fill_rate must be positive",
            boxes=[],
            metrics={
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
            },
        )

    box_volume = box_type.inner_L * box_type.inner_W * box_type.inner_H
    max_volume = box_volume * fill_rate
    item_weights = {item.id: item.weight for item in items}
    item_volumes = {item.id: _volume(item) for item in items}
    expanded = _expand_items(items)
    expanded.sort(key=lambda item: item.weight, reverse=True)

    boxes: list[BoxState] = []
    for item in expanded:
        if item.weight > box_type.max_weight:
            return PackingPlan(
                status="infeasible",
                reason=f"infeasible: item {item.id} overweight",
                boxes=[],
                metrics={
                    "total_weight": total_weight,
                    "box_count": 0.0,
                    "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
                },
            )
        if not _fits_with_rotation(item, box_type, allow_rotate):
            return PackingPlan(
                status="infeasible",
                reason=f"infeasible: item {item.id} oversize",
                boxes=[],
                metrics={
                    "total_weight": total_weight,
                    "box_count": 0.0,
                    "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
                },
            )
        item_volume = _volume(item)
        if item_volume > max_volume:
            return PackingPlan(
                status="infeasible",
                reason=f"infeasible: item {item.id} over volume",
                boxes=[],
                metrics={
                    "total_weight": total_weight,
                    "box_count": 0.0,
                    "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
                },
            )

        best_idx = None
        best_remaining = None
        for idx, box in enumerate(boxes):
            new_weight = box.total_weight + item.weight
            new_volume = box.total_volume + item_volume
            if new_weight > box_type.max_weight:
                continue
            if new_volume > max_volume:
                continue
            remaining = box_type.max_weight - new_weight
            if best_remaining is None or remaining < best_remaining:
                best_remaining = remaining
                best_idx = idx

        if best_idx is None:
            boxes.append(
                BoxState(
                    total_weight=item.weight,
                    total_volume=item_volume,
                    items={item.id: 1},
                )
            )
        else:
            box = boxes[best_idx]
            box.total_weight += item.weight
            box.total_volume += item_volume
            box.items[item.id] = box.items.get(item.id, 0) + 1

    boxes = repair_underweight(
        boxes,
        item_weights,
        item_volumes,
        box_type.min_weight,
        box_type.max_weight,
        max_volume,
    )

    packed_boxes: list[PackedBox] = []
    for box in boxes:
        packed_items = [PackedItem(item_id=item_id, qty=qty) for item_id, qty in box.items.items()]
        packed_boxes.append(
            PackedBox(
                box_type_id=box_type.id,
                total_weight=box.total_weight,
                items=packed_items,
            )
        )

    return PackingPlan(
        status="ok",
        reason="",
        boxes=packed_boxes,
        metrics={
            "total_weight": total_weight,
            "box_count": float(len(packed_boxes)),
            "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
        },
    )


def solve(
    items: list[Item],
    box_type: BoxType,
    *,
    allow_rotate: bool = True,
    fill_rate: float = 0.90,
) -> PackingPlan:
    return pack_order(
        items,
        box_type,
        allow_rotate=allow_rotate,
        fill_rate=fill_rate,
    )
