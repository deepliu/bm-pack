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
                allow_rotation=allow_rotation,
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
        item_by_id = {item.id: item for item in items}
        box_type_by_id = {bt.id: bt for bt in box_types}
        util_penalty = 0.0
        sku_penalty = 0
        box_volume_total = 0.0
        for packed_box in plan.boxes:
            box_type_obj = box_type_by_id[packed_box.box_type_id]
            box_volume = box_type_obj.inner_L * box_type_obj.inner_W * box_type_obj.inner_H
            box_volume_total += box_volume
            total_volume = 0.0
            sku_count = 0
            for packed_item in packed_box.items:
                item = item_by_id[packed_item.item_id]
                total_volume += _volume(item) * packed_item.qty
                sku_count += 1
            util = total_volume / box_volume if box_volume > 0 else 0.0
            if util < utilization_target:
                util_penalty += (utilization_target - util)
            sku_penalty += max(0, sku_count - 1)
        box_count_penalty = float(max(0, plan.metrics.get("box_count", 0.0) - float(b_min)))
        return (box_count_penalty, sku_penalty, util_penalty, box_volume_total)

    def _validate_plan(plan: PackingPlan) -> PackingPlan:
        if not geometry_check:
            return plan
        if not plan.boxes:
            return plan
        box_type_by_id = {bt.id: bt for bt in box_types}
        for idx, packed_box in enumerate(plan.boxes, start=1):
            box_type_obj = box_type_by_id[packed_box.box_type_id]
            visualize_path = None
            if geometry_visualize_dir:
                visualize_path = str(
                    Path(geometry_visualize_dir) / f"{packed_box.box_type_id}_box_{idx}.png"
                )
            geom = geometry_validate(
                packed_box,
                box_type_obj,
                {item.id: item for item in items},
                visualize_path=visualize_path,
                allow_rotation=allow_rotation,
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

    def _optimize_box_types(plan: PackingPlan) -> PackingPlan:
        if plan.status != "ok" or not plan.boxes:
            return plan

        item_by_id = {item.id: item for item in items}
        fill_rate_plan = float(plan.metrics.get("fill_rate", fill_rate))

        optimized_boxes: list[PackedBox] = []
        for packed_box in plan.boxes:
            items_weight = 0.0
            items_volume = 0.0
            for packed_item in packed_box.items:
                item = item_by_id[packed_item.item_id]
                items_weight += item.weight * packed_item.qty
                items_volume += _volume(item) * packed_item.qty

            current_box_type = next(
                (bt for bt in box_types if bt.id == packed_box.box_type_id), None
            )
            if current_box_type is None:
                optimized_boxes.append(packed_box)
                continue

            candidates: list[BoxType] = []
            for bt in box_types:
                total_weight = items_weight + bt.tare_weight
                if not (bt.min_weight <= total_weight <= bt.max_weight):
                    continue
                if any(
                    not _fits(item_by_id[pi.item_id], bt) for pi in packed_box.items
                ):
                    continue
                box_volume = bt.inner_L * bt.inner_W * bt.inner_H
                if items_volume > box_volume * fill_rate_plan:
                    continue
                candidates.append(bt)

            if not candidates:
                optimized_boxes.append(packed_box)
                continue

            candidates.sort(
                key=lambda bt: (bt.inner_L * bt.inner_W * bt.inner_H, bt.max_weight)
            )
            chosen = current_box_type
            for candidate in candidates:
                candidate_box = PackedBox(
                    box_type_id=candidate.id,
                    total_weight=items_weight + candidate.tare_weight,
                    items=packed_box.items,
                )
                if geometry_check:
                    geom = geometry_validate(
                        candidate_box,
                        candidate,
                        item_by_id,
                        allow_rotation=allow_rotation,
                    )
                    if not geom.ok:
                        continue
                chosen = candidate
                break
            optimized_boxes.append(
                PackedBox(
                    box_type_id=chosen.id,
                    total_weight=items_weight + chosen.tare_weight,
                    items=packed_box.items,
                )
            )

        return PackingPlan(
            status="ok",
            reason="",
            boxes=optimized_boxes,
            metrics=dict(plan.metrics),
            suggestions=[],
        )

    def _optimize_quantities(plan: PackingPlan) -> PackingPlan:
        if plan.status != "ok" or not plan.boxes:
            return plan

        item_by_id = {item.id: item for item in items}
        fill_rate_plan = float(plan.metrics.get("fill_rate", fill_rate))

        mutable_boxes: list[BoxState] = []
        for packed_box in plan.boxes:
            bt = next((b for b in box_types if b.id == packed_box.box_type_id), None)
            if bt is None:
                continue
            box_volume = bt.inner_L * bt.inner_W * bt.inner_H
            max_volume = box_volume * fill_rate_plan
            items_map: dict[str, int] = {}
            total_weight = bt.tare_weight
            total_volume = 0.0
            for packed_item in packed_box.items:
                items_map[packed_item.item_id] = packed_item.qty
                item = item_by_id[packed_item.item_id]
                total_weight += item.weight * packed_item.qty
                total_volume += _volume(item) * packed_item.qty
            mutable_boxes.append(
                BoxState(
                    box_type_id=bt.id,
                    min_weight=bt.min_weight,
                    max_weight=bt.max_weight,
                    tare_weight=bt.tare_weight,
                    box_volume=box_volume,
                    max_volume=max_volume,
                    total_weight=total_weight,
                    total_volume=total_volume,
                    items=items_map,
                )
            )

        def _can_move(src: BoxState, dst: BoxState, sku_id: str, qty: int) -> bool:
            if qty <= 0:
                return False
            if src.items.get(sku_id, 0) < qty:
                return False
            item = item_by_id[sku_id]
            weight_delta = item.weight * qty
            volume_delta = _volume(item) * qty
            if dst.total_weight + weight_delta > dst.max_weight:
                return False
            if dst.total_volume + volume_delta > dst.max_volume:
                return False
            if src.total_weight - weight_delta < src.min_weight:
                return False
            if src.total_volume - volume_delta < 0:
                return False
            return True

        def _move(src: BoxState, dst: BoxState, sku_id: str, qty: int) -> None:
            item = item_by_id[sku_id]
            weight_delta = item.weight * qty
            volume_delta = _volume(item) * qty
            src.items[sku_id] -= qty
            if src.items[sku_id] <= 0:
                del src.items[sku_id]
            dst.items[sku_id] = dst.items.get(sku_id, 0) + qty
            src.total_weight -= weight_delta
            src.total_volume -= volume_delta
            dst.total_weight += weight_delta
            dst.total_volume += volume_delta

        all_skus = sorted({pi.item_id for b in plan.boxes for pi in b.items})
        for sku_id in all_skus:
            boxes_with_sku = [b for b in mutable_boxes if b.items.get(sku_id, 0) > 0]
            if len(boxes_with_sku) < 2:
                continue
            remainders = [b.items[sku_id] % 5 for b in boxes_with_sku]
            if all(r == 0 for r in remainders):
                continue

            def _sorted_collectors() -> list[BoxState]:
                return sorted(
                    boxes_with_sku,
                    key=lambda b: (
                        -(b.max_weight - b.total_weight),
                        -(b.max_volume - b.total_volume),
                    ),
                )

            # Pass 1: move remainder out to a collector.
            for box in boxes_with_sku:
                rem = box.items[sku_id] % 5
                if rem == 0:
                    continue
                for collector in _sorted_collectors():
                    if collector is box:
                        continue
                    if _can_move(box, collector, sku_id, rem):
                        _move(box, collector, sku_id, rem)
                        break

            # Pass 2: try to add to box to reach next multiple.
            for box in boxes_with_sku:
                rem = box.items.get(sku_id, 0) % 5
                if rem == 0:
                    continue
                need = 5 - rem
                donors = sorted(
                    boxes_with_sku,
                    key=lambda b: b.items.get(sku_id, 0),
                    reverse=True,
                )
                for donor in donors:
                    if donor is box:
                        continue
                    if _can_move(donor, box, sku_id, need):
                        _move(donor, box, sku_id, need)
                        break

        packed_boxes: list[PackedBox] = []
        for box in mutable_boxes:
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
            metrics=dict(plan.metrics),
            suggestions=[],
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

    def _utilization_tiers(base: float) -> list[float]:
        tiers = [base, 0.75, 0.70, 0.60]
        seen: set[float] = set()
        ordered: list[float] = []
        for value in tiers:
            rounded = round(float(value), 3)
            if rounded in seen:
                continue
            seen.add(rounded)
            ordered.append(float(value))
        return ordered

    def _target_box_counts(b_min: int, b_max: int, slack: int) -> list[int]:
        candidates = [b_min + offset for offset in range(max(0, slack) + 1)]
        unique: list[int] = []
        seen: set[int] = set()
        for count in candidates:
            if count in seen:
                continue
            seen.add(count)
            if b_max >= 0 and count > b_max:
                continue
            unique.append(count)
        return unique

    best_plan: Optional[PackingPlan] = None
    best_score: Optional[tuple[float, int, float, float]] = None
    best_infeasible: Optional[PackingPlan] = None
    b_min = feasibility.b_min
    b_max = feasibility.b_max
    target_slack = b_max - b_min if geometry_check else max_box_slack
    targets = _target_box_counts(b_min, b_max, target_slack)
    util_tiers = _utilization_tiers(utilization_target)

    def _record(plan: PackingPlan) -> None:
        nonlocal best_plan, best_score, best_infeasible
        if plan.status != "ok":
            if best_infeasible is None:
                best_infeasible = plan
            return
        candidate = _optimize_box_types(plan)
        candidate = _validate_plan(candidate)
        if candidate.status != "ok":
            if best_infeasible is None or best_infeasible.reason != candidate.reason:
                best_infeasible = candidate
            return
        quantity_candidate = _validate_plan(_optimize_quantities(candidate))
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
        expanded_targets = _target_box_counts(b_min, b_max, b_max - b_min)
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
    return best_plan
