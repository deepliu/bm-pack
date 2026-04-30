from __future__ import annotations

from .geometry_engine import GeometryEngine
from .repair import BoxState
from .state import box_state_to_packed_box, item_fits_box, item_volume
from .types import BoxType, Item, PackedBox, PackingPlan


def optimize_box_types(
    plan: PackingPlan,
    *,
    items_by_id: dict[str, Item],
    box_types: list[BoxType],
    geometry_engine: GeometryEngine,
    fill_rate: float,
) -> PackingPlan:
    if plan.status != "ok" or not plan.boxes:
        return plan

    optimized_boxes: list[PackedBox] = []
    for packed_box in plan.boxes:
        items_weight = 0.0
        items_volume = 0.0
        for packed_item in packed_box.items:
            item = items_by_id[packed_item.item_id]
            items_weight += item.weight * packed_item.qty
            items_volume += item_volume(item) * packed_item.qty

        current_box_type = next(
            (box_type for box_type in box_types if box_type.id == packed_box.box_type_id),
            None,
        )
        if current_box_type is None:
            optimized_boxes.append(packed_box)
            continue

        candidates: list[BoxType] = []
        for box_type in box_types:
            total_weight = items_weight + box_type.tare_weight
            if not (box_type.min_weight <= total_weight <= box_type.max_weight):
                continue
            if any(
                not item_fits_box(items_by_id[pi.item_id], box_type)
                for pi in packed_box.items
            ):
                continue
            box_volume = box_type.inner_L * box_type.inner_W * box_type.inner_H
            if items_volume > box_volume * fill_rate:
                continue
            candidates.append(box_type)

        if not candidates:
            optimized_boxes.append(packed_box)
            continue

        candidates.sort(
            key=lambda box_type: (
                box_type.inner_L * box_type.inner_W * box_type.inner_H,
                box_type.max_weight,
            )
        )
        chosen = current_box_type
        for candidate in candidates:
            candidate_box = PackedBox(
                box_type_id=candidate.id,
                total_weight=items_weight + candidate.tare_weight,
                items=packed_box.items,
            )
            if not geometry_engine.validate_box(candidate_box, candidate).ok:
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


def optimize_quantities(
    plan: PackingPlan,
    *,
    items_by_id: dict[str, Item],
    box_types_by_id: dict[str, BoxType],
    geometry_engine: GeometryEngine,
    fill_rate: float,
) -> PackingPlan:
    if plan.status != "ok" or not plan.boxes:
        return plan

    mutable_boxes: list[BoxState] = []
    for packed_box in plan.boxes:
        box_type = box_types_by_id.get(packed_box.box_type_id)
        if box_type is None:
            continue
        box_volume = box_type.inner_L * box_type.inner_W * box_type.inner_H
        items_map: dict[str, int] = {}
        total_weight = box_type.tare_weight
        total_volume = 0.0
        for packed_item in packed_box.items:
            items_map[packed_item.item_id] = packed_item.qty
            item = items_by_id[packed_item.item_id]
            total_weight += item.weight * packed_item.qty
            total_volume += item_volume(item) * packed_item.qty
        mutable_boxes.append(
            BoxState(
                box_type_id=box_type.id,
                min_weight=box_type.min_weight,
                max_weight=box_type.max_weight,
                tare_weight=box_type.tare_weight,
                box_volume=box_volume,
                max_volume=box_volume * fill_rate,
                total_weight=total_weight,
                total_volume=total_volume,
                items=items_map,
            )
        )

    def _can_move(src: BoxState, dst: BoxState, sku_id: str, qty: int) -> bool:
        if qty <= 0 or src.items.get(sku_id, 0) < qty:
            return False
        item = items_by_id[sku_id]
        weight_delta = item.weight * qty
        volume_delta = item_volume(item) * qty
        return (
            dst.total_weight + weight_delta <= dst.max_weight
            and dst.total_volume + volume_delta <= dst.max_volume
            and src.total_weight - weight_delta >= src.min_weight
            and src.total_volume - volume_delta >= 0
        )

    def _move(src: BoxState, dst: BoxState, sku_id: str, qty: int) -> None:
        item = items_by_id[sku_id]
        weight_delta = item.weight * qty
        volume_delta = item_volume(item) * qty
        src.items[sku_id] -= qty
        if src.items[sku_id] <= 0:
            del src.items[sku_id]
        dst.items[sku_id] = dst.items.get(sku_id, 0) + qty
        src.total_weight -= weight_delta
        src.total_volume -= volume_delta
        dst.total_weight += weight_delta
        dst.total_volume += volume_delta

    def _geometry_ok() -> bool:
        packed_boxes = [box_state_to_packed_box(box) for box in mutable_boxes]
        return geometry_engine.validate_plan(
            packed_boxes,
            box_types_by_id,
            visualize=False,
        )[0]

    def _try_move(src: BoxState, dst: BoxState, sku_id: str, qty: int) -> bool:
        if not _can_move(src, dst, sku_id, qty):
            return False
        _move(src, dst, sku_id, qty)
        if _geometry_ok():
            return True
        _move(dst, src, sku_id, qty)
        return False

    all_skus = sorted({pi.item_id for box in plan.boxes for pi in box.items})
    for sku_id in all_skus:
        boxes_with_sku = [box for box in mutable_boxes if box.items.get(sku_id, 0) > 0]
        if len(boxes_with_sku) < 2:
            continue
        if all(box.items[sku_id] % 5 == 0 for box in boxes_with_sku):
            continue

        def _sorted_collectors() -> list[BoxState]:
            return sorted(
                boxes_with_sku,
                key=lambda box: (
                    -(box.max_weight - box.total_weight),
                    -(box.max_volume - box.total_volume),
                ),
            )

        for box in boxes_with_sku:
            rem = box.items[sku_id] % 5
            if rem == 0:
                continue
            for collector in _sorted_collectors():
                if collector is box:
                    continue
                if _try_move(box, collector, sku_id, rem):
                    break

        for box in boxes_with_sku:
            rem = box.items.get(sku_id, 0) % 5
            if rem == 0:
                continue
            need = 5 - rem
            donors = sorted(
                boxes_with_sku,
                key=lambda donor: donor.items.get(sku_id, 0),
                reverse=True,
            )
            for donor in donors:
                if donor is box:
                    continue
                if _try_move(donor, box, sku_id, need):
                    break

    packed_boxes = [box_state_to_packed_box(box) for box in mutable_boxes]
    return PackingPlan(
        status="ok",
        reason="",
        boxes=packed_boxes,
        metrics=dict(plan.metrics),
        suggestions=[],
    )
