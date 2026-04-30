from __future__ import annotations

from .state import box_volume, item_volume
from .types import BoxType, Item, PackingPlan


def utilization_tiers(base: float) -> list[float]:
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


def target_box_counts(b_min: int, b_max: int, slack: int) -> list[int]:
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


def score_plan(
    plan: PackingPlan,
    *,
    items_by_id: dict[str, Item],
    box_types_by_id: dict[str, BoxType],
    b_min: int,
    utilization_target: float,
) -> tuple[float, int, float, float]:
    util_penalty = 0.0
    sku_penalty = 0
    box_volume_total = 0.0

    for packed_box in plan.boxes:
        box_type = box_types_by_id[packed_box.box_type_id]
        volume = box_volume(box_type)
        box_volume_total += volume
        total_volume = 0.0
        sku_count = 0
        for packed_item in packed_box.items:
            item = items_by_id[packed_item.item_id]
            total_volume += item_volume(item) * packed_item.qty
            sku_count += 1
        util = total_volume / volume if volume > 0 else 0.0
        if util < utilization_target:
            util_penalty += utilization_target - util
        sku_penalty += max(0, sku_count - 1)

    box_count_penalty = float(
        max(0, plan.metrics.get("box_count", 0.0) - float(b_min))
    )
    return (box_count_penalty, sku_penalty, util_penalty, box_volume_total)
