from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Iterable, List, Optional, Union

from .feasibility import (
    FeasibilityResult,
    _build_delta_suggestions,
    _build_suggestions,
    feasibility_bounds,
)
from .geometry import geometry_validate
from .repair import BoxState, repair_underweight
from .types import BoxType, Item, PackedBox, PackedItem, PackingPlan


def _volume(item: Item) -> float:
    return item.L * item.W * item.H


def _fits(item: Item, box: BoxType) -> bool:
    dims = (item.L, item.W, item.H)
    box_dims = (box.inner_L, box.inner_W, box.inner_H)
    return all(d <= b for d, b in zip(dims, box_dims))


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


def _compute_feasibility(items: list[Item], box_types: list[BoxType]) -> FeasibilityResult:
    total_weight = sum(item.weight * item.qty for item in items)
    max_weight = max(box_type.max_weight - box_type.tare_weight for box_type in box_types)
    min_weight = min(max(0.0, box_type.min_weight - box_type.tare_weight) for box_type in box_types)
    b_min, b_max = feasibility_bounds(total_weight, min_weight, max_weight)
    if b_min > b_max:
        reason = (
            f"infeasible: total_weight={total_weight:.3f}, "
            f"b_min={b_min}, b_max={b_max}"
        )
        return FeasibilityResult(
            ok=False,
            total_weight=total_weight,
            b_min=b_min,
            b_max=b_max,
            reason=reason,
            suggestions=_build_suggestions(
                items,
                total_weight=total_weight,
                min_weight=min_weight,
                max_weight=max_weight,
                b_min=b_min,
                b_max=b_max,
            ),
        )
    return FeasibilityResult(
        ok=True,
        total_weight=total_weight,
        b_min=b_min,
        b_max=b_max,
        reason="",
        suggestions=[],
    )


def _select_new_box_type(
    item: Item,
    box_types: List[BoxType],
    fill_rate: float,
    utilization_target: float,
) -> Optional[BoxType]:
    candidates: list[BoxType] = []
    item_volume = _volume(item)
    for box_type in box_types:
        item_capacity = box_type.max_weight - box_type.tare_weight
        if item_capacity <= 0:
            continue
        box_volume = box_type.inner_L * box_type.inner_W * box_type.inner_H
        max_volume = box_volume * fill_rate
        if item.weight > item_capacity:
            continue
        if item_volume > max_volume:
            continue
        if not _fits(item, box_type):
            continue
        candidates.append(box_type)
    if not candidates:
        return None
    def _score(bt: BoxType) -> tuple[float, float]:
        box_volume = bt.inner_L * bt.inner_W * bt.inner_H
        util = item_volume / box_volume if box_volume > 0 else 0.0
        util_penalty = 0.0 if util >= utilization_target else (utilization_target - util)
        return (util_penalty, box_volume)

    candidates.sort(key=_score)
    return candidates[0]


def pack_order(
    items: list[Item],
    box_type: Union[BoxType, List[BoxType]],
    *,
    fill_rate: float = 0.90,
    utilization_target: float = 0.80,
    geometry_check: bool = False,
    geometry_visualize_dir: Optional[str] = None,
) -> PackingPlan:
    box_types = box_type if isinstance(box_type, list) else [box_type]
    if not box_types:
        return PackingPlan(
            status="infeasible",
            reason="infeasible: no box types provided",
            boxes=[],
            metrics={
                "total_weight": 0.0,
                "box_count": 0.0,
                "lower_bound_by_weight": 0.0,
            },
            suggestions=[],
        )

    feasibility = _compute_feasibility(items, box_types)
    total_weight = feasibility.total_weight
    if not feasibility.ok:
        return PackingPlan(
            status="infeasible",
            reason=feasibility.reason,
            boxes=[],
            metrics={
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(
                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                ),
            },
            suggestions=feasibility.suggestions,
        )

    if fill_rate <= 0:
        return PackingPlan(
            status="infeasible",
            reason="infeasible: fill_rate must be positive",
            boxes=[],
            metrics={
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(
                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                ),
            },
            suggestions=[],
        )

    item_weights = {item.id: item.weight for item in items}
    item_volumes = {item.id: _volume(item) for item in items}
    expanded = _expand_items(items)
    expanded.sort(key=lambda item: (_volume(item), item.weight), reverse=True)

    boxes: list[BoxState] = []
    max_allowed_weight = max(box_type.max_weight - box_type.tare_weight for box_type in box_types)
    for item in expanded:
        if item.weight > max_allowed_weight:
            return PackingPlan(
                status="infeasible",
                reason=f"infeasible: item {item.id} overweight",
                boxes=[],
                metrics={
                    "total_weight": total_weight,
                    "box_count": 0.0,
                    "lower_bound_by_weight": float(ceil(total_weight / max_allowed_weight)),
                },
                suggestions=[],
            )
        item_volume = _volume(item)
        best_idx = None
        best_score = None
        best_util = None
        for idx, box in enumerate(boxes):
            new_weight = box.total_weight + item.weight
            new_volume = box.total_volume + item_volume
            if new_weight > box.max_weight:
                continue
            if new_volume > box.max_volume:
                continue
            util = new_volume / box.box_volume if box.box_volume > 0 else 0.0
            util_penalty = 0.0 if util >= utilization_target else (utilization_target - util)
            sku_penalty = 0.0
            if box.items and item.id not in box.items:
                sku_penalty = 0.1
            score = (util_penalty * 10.0) + sku_penalty
            if best_score is None or score < best_score or (
                score == best_score and (best_util is None or util > best_util)
            ):
                best_score = score
                best_idx = idx
                best_util = util

        if best_idx is None:
            selected_box_type = _select_new_box_type(
                item, box_types, fill_rate, utilization_target
            )
            if selected_box_type is None:
                return PackingPlan(
                    status="infeasible",
                    reason=f"infeasible: item {item.id} oversize",
                    boxes=[],
                    metrics={
                        "total_weight": total_weight,
                        "box_count": 0.0,
                        "lower_bound_by_weight": float(ceil(total_weight / max_allowed_weight)),
                    },
                    suggestions=[],
                )
            box_volume = (
                selected_box_type.inner_L
                * selected_box_type.inner_W
                * selected_box_type.inner_H
            )
            max_volume = box_volume * fill_rate
            item_capacity = selected_box_type.max_weight - selected_box_type.tare_weight
            if item_capacity <= 0:
                return PackingPlan(
                    status="infeasible",
                    reason=f"infeasible: box {selected_box_type.id} has no capacity after tare",
                    boxes=[],
                    metrics={
                        "total_weight": total_weight,
                        "box_count": 0.0,
                        "lower_bound_by_weight": float(ceil(total_weight / max_allowed_weight)),
                    },
                    suggestions=[],
                )
            if item_volume > max_volume:
                return PackingPlan(
                    status="infeasible",
                    reason=f"infeasible: item {item.id} cannot fit by volume",
                    boxes=[],
                    metrics={
                        "total_weight": total_weight,
                        "box_count": 0.0,
                        "lower_bound_by_weight": float(ceil(total_weight / max_allowed_weight)),
                    },
                    suggestions=[],
                )
            boxes.append(
                BoxState(
                    box_type_id=selected_box_type.id,
                    min_weight=selected_box_type.min_weight,
                    max_weight=selected_box_type.max_weight,
                    tare_weight=selected_box_type.tare_weight,
                    box_volume=box_volume,
                    max_volume=max_volume,
                    total_weight=item.weight + selected_box_type.tare_weight,
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
    )

    if any(
        box.total_weight < box.min_weight or box.total_weight > box.max_weight
        for box in boxes
    ):
        deficit = sum(
            max(0.0, box.min_weight - box.total_weight)
            for box in boxes
            if box.total_weight < box.min_weight
        )
        max_weight = max(bt.max_weight - bt.tare_weight for bt in box_types)
        min_weight = min(max(0.0, bt.min_weight - bt.tare_weight) for bt in box_types)
        if max_weight <= 0 or min_weight <= 0:
            reduce_suggestions = []
        else:
            b_max = int(total_weight // min_weight)
            if b_max >= 1:
                target = max_weight * b_max
                reduce_delta = max(0.0, total_weight - target)
            else:
                reduce_delta = 0.0
            reduce_suggestions = _build_delta_suggestions(
                items,
                delta=reduce_delta,
                action="reduce",
                recommended_box_count=b_max,
            )
        return PackingPlan(
            status="infeasible",
            reason="infeasible: underweight boxes remain after repair",
            boxes=[],
            metrics={
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(
                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                ),
            },
            suggestions=_build_delta_suggestions(
                items,
                delta=deficit,
                action="increase",
                recommended_box_count=len(boxes),
            )
            + reduce_suggestions,
        )

    packed_boxes: list[PackedBox] = []
    box_type_by_id = {bt.id: bt for bt in box_types}
    for box in boxes:
        packed_items = [PackedItem(item_id=item_id, qty=qty) for item_id, qty in box.items.items()]
        packed_box = PackedBox(
            box_type_id=box.box_type_id,
            total_weight=box.total_weight,
            items=packed_items,
        )
        if geometry_check:
            box_type_obj = box_type_by_id[box.box_type_id]
            visualize_path = None
            if geometry_visualize_dir:
                visualize_path = str(
                    Path(geometry_visualize_dir) / f"{box.box_type_id}_box_{len(packed_boxes)+1}.png"
                )
            geom = geometry_validate(
                packed_box,
                box_type_obj,
                {item.id: item for item in items},
                visualize_path=visualize_path,
            )
            if not geom.ok:
                return PackingPlan(
                    status="infeasible",
                    reason=geom.reason,
                    boxes=[],
                    metrics={
                        "total_weight": total_weight,
                        "box_count": 0.0,
                        "lower_bound_by_weight": float(
                            ceil(total_weight / max(bt.max_weight for bt in box_types))
                        ),
                    },
                    suggestions=[],
                )

        packed_boxes.append(
            PackedBox(
                box_type_id=packed_box.box_type_id,
                total_weight=packed_box.total_weight,
                items=packed_box.items,
            )
        )

    return PackingPlan(
        status="ok",
        reason="",
        boxes=packed_boxes,
        metrics={
            "total_weight": total_weight,
            "box_count": float(len(packed_boxes)),
            "lower_bound_by_weight": float(
                ceil(total_weight / max(bt.max_weight for bt in box_types))
            ),
        },
        suggestions=[],
    )


def solve(
    items: list[Item],
    box_type: Union[BoxType, List[BoxType]],
    *,
    fill_rate: float = 0.90,
    utilization_target: float = 0.80,
    geometry_check: bool = False,
    geometry_visualize_dir: Optional[str] = None,
) -> PackingPlan:
    return pack_order(
        items,
        box_type,
        fill_rate=fill_rate,
        utilization_target=utilization_target,
        geometry_check=geometry_check,
        geometry_visualize_dir=geometry_visualize_dir,
    )
