from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Iterable

from .repair import BoxState
from .types import BoxType, Item, PackedBox, PackedItem, PackingPlan


def item_volume(item: Item) -> float:
    return item.L * item.W * item.H


def box_volume(box_type: BoxType) -> float:
    return box_type.inner_L * box_type.inner_W * box_type.inner_H


def item_fits_box(item: Item, box_type: BoxType) -> bool:
    return (
        item.L <= box_type.inner_L
        and item.W <= box_type.inner_W
        and item.H <= box_type.inner_H
    )


def order_item_weight(items: Iterable[Item]) -> float:
    return sum(item.weight * item.qty for item in items)


def expand_items(items: Iterable[Item]) -> list[Item]:
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


@dataclass
class MutableBox:
    box_type: BoxType
    items: dict[str, int] = field(default_factory=dict)
    items_weight: float = 0.0
    items_volume: float = 0.0

    @property
    def box_type_id(self) -> str:
        return self.box_type.id

    @property
    def tare_weight(self) -> float:
        return self.box_type.tare_weight

    @property
    def total_weight(self) -> float:
        return self.items_weight + self.tare_weight

    @property
    def min_weight(self) -> float:
        return self.box_type.min_weight

    @property
    def max_weight(self) -> float:
        return self.box_type.max_weight

    @property
    def box_volume(self) -> float:
        return box_volume(self.box_type)

    def to_packed_box(self) -> PackedBox:
        return PackedBox(
            box_type_id=self.box_type.id,
            total_weight=self.total_weight,
            items=[
                PackedItem(item_id=item_id, qty=qty)
                for item_id, qty in self.items.items()
                if qty > 0
            ],
        )

    def to_box_state(self, fill_rate: float) -> BoxState:
        volume = self.box_volume
        return BoxState(
            box_type_id=self.box_type.id,
            min_weight=self.box_type.min_weight,
            max_weight=self.box_type.max_weight,
            tare_weight=self.box_type.tare_weight,
            box_volume=volume,
            max_volume=volume * fill_rate,
            total_weight=self.total_weight,
            total_volume=self.items_volume,
            items=dict(self.items),
        )


@dataclass
class PackingState:
    boxes: list[MutableBox]
    total_items_weight: float

    def to_plan(self, *, metrics: dict[str, float] | None = None) -> PackingPlan:
        packed_boxes = [box.to_packed_box() for box in self.boxes]
        plan_metrics = {
            "total_weight": self.total_items_weight,
            "box_count": float(len(packed_boxes)),
            "lower_bound_by_weight": 0.0,
        }
        if metrics:
            plan_metrics.update(metrics)
        return PackingPlan(
            status="ok",
            reason="",
            boxes=packed_boxes,
            metrics=plan_metrics,
            suggestions=[],
        )


def box_state_to_packed_box(box: BoxState) -> PackedBox:
    return PackedBox(
        box_type_id=box.box_type_id,
        total_weight=box.total_weight,
        items=[
            PackedItem(item_id=item_id, qty=qty)
            for item_id, qty in box.items.items()
            if qty > 0
        ],
    )


def box_states_to_plan(
    boxes: list[BoxState],
    *,
    total_items_weight: float,
    max_box_weight: float,
    metrics_extra: dict[str, float] | None = None,
) -> PackingPlan:
    packed_boxes = [box_state_to_packed_box(box) for box in boxes]
    metrics = {
        "total_weight": total_items_weight,
        "box_count": float(len(packed_boxes)),
        "lower_bound_by_weight": float(ceil(total_items_weight / max_box_weight)),
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


def plan_quantities(plan: PackingPlan) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for packed_box in plan.boxes:
        for packed_item in packed_box.items:
            quantities[packed_item.item_id] = (
                quantities.get(packed_item.item_id, 0) + packed_item.qty
            )
    return quantities
