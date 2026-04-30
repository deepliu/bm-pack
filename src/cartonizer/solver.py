from __future__ import annotations

from math import ceil
from typing import Iterable, List, Optional, Union

from .feasibility import (
    FeasibilityResult,
    _build_delta_suggestions,
    _build_suggestions,
    feasibility_bounds,
)
from .geometry_engine import GeometryEngine
from .optimizers import optimize_box_types, optimize_quantities
from .repair import BoxState, repair_underweight
from .search import score_plan, target_box_counts, utilization_tiers
from .state import (
    box_state_to_packed_box,
    expand_items,
    item_fits_box,
    item_volume,
    order_item_weight,
)
from .types import BoxType, Item, PackedBox, PackedItem, PackingPlan


def _volume(item: Item) -> float:
    return item_volume(item)


def _fits(item: Item, box: BoxType) -> bool:
    return item_fits_box(item, box)


def _expand_items(items: Iterable[Item]) -> list[Item]:
    return expand_items(items)


def _compute_feasibility(items: list[Item], box_types: list[BoxType]) -> FeasibilityResult:
    total_weight = order_item_weight(items)
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
    *,
    prefer_large_box: bool = False,
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
        if prefer_large_box:
            return (-box_volume, -bt.max_weight)
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
    target_box_count: Optional[int] = None,
    placement_mode: str = "utilization",
    prefer_large_box: bool = False,
    max_sku_types: Optional[int] = 3,
    geometry_check: bool = False,
    geometry_visualize_dir: Optional[str] = None,
    allow_rotation: bool = False,
    metrics_extra: Optional[dict[str, float]] = None,
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
            if max_sku_types is not None and item.id not in box.items:
                if len(box.items) + 1 > max_sku_types:
                    continue
            util = new_volume / box.box_volume if box.box_volume > 0 else 0.0
            new_sku_penalty = 0.0
            if max_sku_types is not None and item.id not in box.items:
                new_sku_penalty = 1000.0
            if placement_mode == "weight":
                remaining = box.max_weight - new_weight
                score = remaining + new_sku_penalty
            else:
                util_penalty = 0.0 if util >= utilization_target else (utilization_target - util)
                sku_penalty = 0.0
                if box.items and item.id not in box.items:
                    sku_penalty = 0.1
                score = (util_penalty * 10.0) + sku_penalty + new_sku_penalty
            if best_score is None or score < best_score or (
                score == best_score and (best_util is None or util > best_util)
            ):
                best_score = score
                best_idx = idx
                best_util = util

        if best_idx is None:
            if target_box_count is not None and len(boxes) >= target_box_count:
                return PackingPlan(
                    status="infeasible",
                    reason="infeasible: exceeded target box count",
                    boxes=[],
                    metrics={
                        "total_weight": total_weight,
                        "box_count": 0.0,
                        "lower_bound_by_weight": float(ceil(total_weight / max_allowed_weight)),
                    },
                    suggestions=[],
                )
            selected_box_type = _select_new_box_type(
                item,
                box_types,
                fill_rate,
                utilization_target,
                prefer_large_box=prefer_large_box,
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
        max_sku_types=max_sku_types,
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
            metrics = {
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(
                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                ),
            }
            if metrics_extra:
                metrics.update(metrics_extra)
        return PackingPlan(
            status="infeasible",
            reason="infeasible: underweight boxes remain after repair",
            boxes=[],
            metrics=metrics,
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
    geometry_engine = GeometryEngine(
        items_by_id={item.id: item for item in items},
        enabled=geometry_check,
        allow_rotation=allow_rotation,
        visualize_dir=geometry_visualize_dir,
    )
    for box in boxes:
        packed_box = box_state_to_packed_box(box)
        if geometry_check:
            box_type_obj = box_type_by_id[box.box_type_id]
            geom = geometry_engine.validate_box(
                packed_box,
                box_type_obj,
                sequence=len(packed_boxes) + 1,
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

        packed_boxes.append(packed_box)

    metrics = {
        "total_weight": total_weight,
        "box_count": float(len(packed_boxes)),
        "lower_bound_by_weight": float(
            ceil(total_weight / max(bt.max_weight for bt in box_types))
        ),
    }
    if metrics_extra:
        metrics.update(metrics_extra)
    return PackingPlan(
        status="ok",
        reason="",
        boxes=packed_boxes,
        metrics=metrics,
        suggestions=[],
    )


def solve(
    items: list[Item],
    box_type: Union[BoxType, List[BoxType]],
    *,
    fill_rate: float = 0.90,
    utilization_target: float = 0.80,
    max_box_slack: int = 2,
    max_sku_types: int = 3,
    geometry_check: bool = False,
    geometry_visualize_dir: Optional[str] = None,
    allow_rotation: bool = False,
) -> PackingPlan:
    box_types = box_type if isinstance(box_type, list) else [box_type]
    feasibility = _compute_feasibility(items, box_types)
    total_weight = feasibility.total_weight
    items_by_id = {item.id: item for item in items}
    box_type_by_id = {bt.id: bt for bt in box_types}
    geometry_engine = GeometryEngine(
        items_by_id=items_by_id,
        enabled=geometry_check,
        allow_rotation=allow_rotation,
        visualize_dir=geometry_visualize_dir,
    )
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

    def _score_plan(plan: PackingPlan, b_min: int) -> tuple[float, int, float, float]:
        return score_plan(
            plan,
            items_by_id=items_by_id,
            box_types_by_id=box_type_by_id,
            b_min=b_min,
            utilization_target=utilization_target,
        )

    def _validate_plan(plan: PackingPlan, *, visualize: bool = False) -> PackingPlan:
        if not geometry_check:
            return plan
        if not plan.boxes:
            return plan
        for idx, packed_box in enumerate(plan.boxes, start=1):
            box_type_obj = box_type_by_id[packed_box.box_type_id]
            geom = geometry_engine.validate_box(
                packed_box,
                box_type_obj,
                sequence=idx,
                visualize=visualize,
            )
            if not geom.ok:
                metrics = dict(plan.metrics)
                metrics.update(
                    {
                        "total_weight": total_weight,
                        "box_count": 0.0,
                        "lower_bound_by_weight": float(
                            ceil(total_weight / max(bt.max_weight for bt in box_types))
                        ),
                        "geometry_checked": 1.0,
                    }
                )
                return PackingPlan(
                    status="infeasible",
                    reason=geom.reason,
                    boxes=[],
                    metrics=metrics,
                    suggestions=[],
                )
        metrics = dict(plan.metrics)
        metrics["geometry_checked"] = 1.0
        return PackingPlan(
            status=plan.status,
            reason=plan.reason,
            boxes=plan.boxes,
            metrics=metrics,
            suggestions=plan.suggestions,
        )

    def _pack_by_sku(
        target: int,
        *,
        fill_rate: float,
        utilization_target: float,
        max_sku_types: Optional[int],
    ) -> PackingPlan:
        sku_items = sorted(
            items,
            key=lambda it: (it.weight * it.qty, _volume(it) * it.qty),
            reverse=True,
        )
        boxes: list[BoxState] = []
        ideal_weight = total_weight / target if target > 0 else total_weight
        box_type_by_id = {bt.id: bt for bt in box_types}
        for sku in sku_items:
            if sku.qty <= 0:
                continue
            qty_remaining = sku.qty
            item_volume = _volume(sku)
            while qty_remaining > 0:
                best_idx = None
                best_capacity = None
                best_score = None
                # Prefer boxes that already contain this SKU, then balance weight and keep SKU count low.
                ordered_boxes = list(range(len(boxes)))
                ordered_boxes.sort(
                    key=lambda i: (
                        sku.id not in boxes[i].items,
                        len(boxes[i].items),
                        boxes[i].total_weight,
                    )
                )
                for idx in ordered_boxes:
                    box = boxes[idx]
                    if max_sku_types is not None and sku.id not in box.items:
                        if len(box.items) + 1 > max_sku_types:
                            continue
                    bt = box_type_by_id[box.box_type_id]
                    if not _fits(sku, bt):
                        continue
                    remaining_weight = box.max_weight - box.total_weight
                    remaining_volume = box.max_volume - box.total_volume
                    if remaining_weight <= 0 or remaining_volume <= 0:
                        continue
                    max_by_weight = int(remaining_weight // sku.weight) if sku.weight > 0 else qty_remaining
                    max_by_volume = int(remaining_volume // item_volume) if item_volume > 0 else qty_remaining
                    capacity = min(qty_remaining, max_by_weight, max_by_volume)
                    if capacity <= 0:
                        continue
                    # Aim to balance toward ideal_weight before filling to max.
                    remaining_to_ideal = max(0.0, ideal_weight - box.total_weight)
                    ideal_units = int(remaining_to_ideal // sku.weight) if sku.weight > 0 else capacity
                    target_units = max(1, min(capacity, ideal_units if ideal_units > 0 else capacity))
                    score = (
                        0 if sku.id in box.items else 1,
                        len(box.items),
                        abs((box.total_weight + sku.weight * target_units) - ideal_weight),
                    )
                    if best_score is None or score < best_score:
                        best_score = score
                        best_capacity = target_units
                        best_idx = idx
                if best_idx is None:
                    if target is not None and len(boxes) >= target:
                        return PackingPlan(
                            status="infeasible",
                            reason="infeasible: exceeded target box count",
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
                    selected_box_type = _select_new_box_type(
                        sku,
                        box_types,
                        fill_rate,
                        utilization_target,
                        prefer_large_box=False,
                    )
                    if selected_box_type is None:
                        return PackingPlan(
                            status="infeasible",
                            reason=f"infeasible: item {sku.id} oversize",
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
                                "lower_bound_by_weight": float(
                                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                                ),
                            },
                            suggestions=[],
                        )
                    max_by_weight = int(item_capacity // sku.weight) if sku.weight > 0 else qty_remaining
                    max_by_volume = int(max_volume // item_volume) if item_volume > 0 else qty_remaining
                    count = min(qty_remaining, max_by_weight, max_by_volume)
                    if count <= 0:
                        return PackingPlan(
                            status="infeasible",
                            reason=f"infeasible: item {sku.id} cannot fit by volume",
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
                    boxes.append(
                        BoxState(
                            box_type_id=selected_box_type.id,
                            min_weight=selected_box_type.min_weight,
                            max_weight=selected_box_type.max_weight,
                            tare_weight=selected_box_type.tare_weight,
                            box_volume=box_volume,
                            max_volume=max_volume,
                            total_weight=sku.weight * count + selected_box_type.tare_weight,
                            total_volume=item_volume * count,
                            items={sku.id: count},
                        )
                    )
                    qty_remaining -= count
                else:
                    box = boxes[best_idx]
                    add = best_capacity if best_capacity is not None else 0
                    if add <= 0:
                        return PackingPlan(
                            status="infeasible",
                            reason="infeasible: sku placement failed",
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
                    box.total_weight += sku.weight * add
                    box.total_volume += item_volume * add
                    box.items[sku.id] = box.items.get(sku.id, 0) + add
                    qty_remaining -= add

        boxes = repair_underweight(
            boxes,
            {i.id: i.weight for i in items},
            {i.id: _volume(i) for i in items},
            max_sku_types=max_sku_types,
        )
        if any(
            box.total_weight < box.min_weight or box.total_weight > box.max_weight
            for box in boxes
        ):
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
                suggestions=[],
            )

        packed_boxes: list[PackedBox] = []
        for box in boxes:
            packed_items = [
                PackedItem(item_id=item_id, qty=qty) for item_id, qty in box.items.items()
            ]
            packed_boxes.append(
                PackedBox(
                    box_type_id=box.box_type_id,
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
                "lower_bound_by_weight": float(
                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                ),
            },
            suggestions=[],
        )

    def _choose_universal_box_type() -> Optional[BoxType]:
        candidates: list[BoxType] = []
        for bt in box_types:
            capacity = bt.max_weight - bt.tare_weight
            if capacity <= 0:
                continue
            if all(_fits(it, bt) and it.weight <= capacity for it in items):
                candidates.append(bt)
        if not candidates:
            return None
        candidates.sort(
            key=lambda bt: (-(bt.inner_L * bt.inner_W * bt.inner_H), -bt.max_weight)
        )
        return candidates[0]

    def _pack_by_sku_groups(
        target: int,
        *,
        fill_rate: float,
        max_sku_types: Optional[int],
    ) -> PackingPlan:
        if max_sku_types is None or max_sku_types <= 0:
            return PackingPlan(
                status="infeasible",
                reason="infeasible: max_sku_types not set for sku-grouped packing",
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

        bt = _choose_universal_box_type()
        if bt is None:
            return PackingPlan(
                status="infeasible",
                reason="infeasible: no box type fits all items",
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

        box_volume = bt.inner_L * bt.inner_W * bt.inner_H
        max_volume = box_volume * fill_rate
        boxes: list[BoxState] = [
            BoxState(
                box_type_id=bt.id,
                min_weight=bt.min_weight,
                max_weight=bt.max_weight,
                tare_weight=bt.tare_weight,
                box_volume=box_volume,
                max_volume=max_volume,
                total_weight=bt.tare_weight,
                total_volume=0.0,
                items={},
            )
            for _ in range(target)
        ]

        item_by_id = {it.id: it for it in items}
        sku_order = sorted(
            items,
            key=lambda it: (it.weight * it.qty, _volume(it) * it.qty),
            reverse=True,
        )

        for sku in sku_order:
            for _ in range(sku.qty):
                best_idx = None
                best_score = None
                for idx, box in enumerate(boxes):
                    if sku.id not in box.items and len(box.items) + 1 > max_sku_types:
                        continue
                    new_weight = box.total_weight + sku.weight
                    new_volume = box.total_volume + _volume(sku)
                    if new_weight > box.max_weight or new_volume > box.max_volume:
                        continue
                    score = (
                        0 if sku.id in box.items else 1,
                        len(box.items),
                        box.total_weight,
                    )
                    if best_score is None or score < best_score:
                        best_score = score
                        best_idx = idx
                if best_idx is None:
                    return PackingPlan(
                        status="infeasible",
                        reason="infeasible: sku-grouped packing overflow",
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
                box = boxes[best_idx]
                box.items[sku.id] = box.items.get(sku.id, 0) + 1
                box.total_weight += sku.weight
                box.total_volume += _volume(sku)

        boxes = repair_underweight(
            boxes,
            {i.id: i.weight for i in items},
            {i.id: _volume(i) for i in items},
            max_sku_types=max_sku_types,
        )

        if any(
            box.total_weight < box.min_weight or box.total_weight > box.max_weight
            for box in boxes
        ):
            return PackingPlan(
                status="infeasible",
                reason="infeasible: sku-grouped packing failed after repair",
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

        packed_boxes: list[PackedBox] = []
        for box in boxes:
            packed_items = [
                PackedItem(item_id=item_id, qty=qty) for item_id, qty in box.items.items()
            ]
            packed_boxes.append(
                PackedBox(
                    box_type_id=box.box_type_id,
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
                "lower_bound_by_weight": float(
                    ceil(total_weight / max(bt.max_weight for bt in box_types))
                ),
            },
            suggestions=[],
        )

    best_plan: Optional[PackingPlan] = None
    best_score: Optional[tuple[float, int, float, float]] = None
    best_infeasible: Optional[PackingPlan] = None
    b_min = feasibility.b_min
    b_max = feasibility.b_max
    target_slack = b_max - b_min if geometry_check else max_box_slack
    targets = target_box_counts(b_min, b_max, target_slack)
    util_tiers = utilization_tiers(utilization_target)

    def _record(plan: PackingPlan) -> None:
        nonlocal best_plan, best_score, best_infeasible
        if plan.status != "ok":
            if best_infeasible is None:
                best_infeasible = plan
            return
        candidate = optimize_box_types(
            plan,
            items_by_id=items_by_id,
            box_types=box_types,
            geometry_engine=geometry_engine,
            fill_rate=float(plan.metrics.get("fill_rate", fill_rate)),
        )
        candidate = _validate_plan(candidate)
        if candidate.status != "ok":
            if best_infeasible is None or best_infeasible.reason != candidate.reason:
                best_infeasible = candidate
            return
        quantity_candidate = _validate_plan(
            optimize_quantities(
                candidate,
                items_by_id=items_by_id,
                box_types_by_id=box_type_by_id,
                geometry_engine=geometry_engine,
                fill_rate=float(candidate.metrics.get("fill_rate", fill_rate)),
            )
        )
        if quantity_candidate.status == "ok":
            candidate = quantity_candidate
        score = _score_plan(candidate, b_min)
        if best_score is None or score < best_score:
            best_score = score
            best_plan = candidate

    # Stage A: SKU-grouped packing (primary).
    for sku_limit in (max_sku_types, None):
        for util in util_tiers:
            for target in targets:
                metrics_extra = {
                    "utilization_target": float(util),
                    "fill_rate": float(fill_rate),
                    "target_box_count": float(target),
                    "max_sku_types": float(sku_limit) if sku_limit is not None else 0.0,
                    "sku_limit_relaxed": 0.0 if sku_limit is not None else 1.0,
                    "stage": 1.0,
                }
                if sku_limit is not None:
                    plan = _pack_by_sku_groups(
                        target,
                        fill_rate=fill_rate,
                        max_sku_types=sku_limit,
                    )
                else:
                    plan = _pack_by_sku(
                        target,
                        fill_rate=fill_rate,
                        utilization_target=util,
                        max_sku_types=sku_limit,
                    )
                plan.metrics.update(metrics_extra)
                _record(plan)

    # Stage B: mixed packing fallback if SKU grouping fails.
    if best_plan is None:
        for sku_limit in (max_sku_types, None):
            for util in util_tiers:
                for target in targets:
                    metrics_extra = {
                        "utilization_target": float(util),
                        "fill_rate": float(fill_rate),
                        "target_box_count": float(target),
                        "max_sku_types": float(sku_limit) if sku_limit is not None else 0.0,
                        "sku_limit_relaxed": 0.0 if sku_limit is not None else 1.0,
                        "stage": 2.0,
                    }
                    plan = pack_order(
                        items,
                        box_types,
                        fill_rate=fill_rate,
                        utilization_target=util,
                        target_box_count=target,
                        placement_mode="utilization",
                        prefer_large_box=False,
                        max_sku_types=sku_limit,
                        geometry_check=False,
                        geometry_visualize_dir=None,
                        metrics_extra=metrics_extra,
                    )
                    _record(plan)

    # Stage C: if still infeasible, allow more boxes (up to b_max) and relax SKU limits.
    if best_plan is None and b_max > 0:
        expanded_targets = target_box_counts(b_min, b_max, b_max - b_min)
        relaxed_sku_limits = [max_sku_types + 1, max_sku_types + 2, None]
        for sku_limit in relaxed_sku_limits:
            for util in util_tiers:
                for target in expanded_targets:
                    metrics_extra = {
                        "utilization_target": float(util),
                        "fill_rate": float(fill_rate),
                        "target_box_count": float(target),
                        "max_sku_types": float(sku_limit) if sku_limit is not None else 0.0,
                        "sku_limit_relaxed": 1.0,
                        "stage": 3.0,
                    }
                    plan = pack_order(
                        items,
                        box_types,
                        fill_rate=fill_rate,
                        utilization_target=util,
                        target_box_count=target,
                        placement_mode="utilization",
                        prefer_large_box=False,
                        max_sku_types=sku_limit,
                        geometry_check=False,
                        geometry_visualize_dir=None,
                        metrics_extra=metrics_extra,
                    )
                    _record(plan)

    if best_plan is None:
        return _validate_plan(best_infeasible) if best_infeasible is not None else pack_order(
            items,
            box_types,
            fill_rate=fill_rate,
            utilization_target=utilization_target,
            geometry_check=geometry_check,
            geometry_visualize_dir=geometry_visualize_dir,
            allow_rotation=allow_rotation,
            max_sku_types=max_sku_types,
        )
    if geometry_visualize_dir:
        return _validate_plan(best_plan, visualize=True)
    return best_plan
