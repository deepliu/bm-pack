from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BoxType:
    id: str
    inner_L: float
    inner_W: float
    inner_H: float
    max_weight: float = 22.5
    min_weight: float = 12.0
    tare_weight: float = 0.0
    cost: float | None = None


@dataclass(frozen=True)
class Item:
    id: str
    L: float
    W: float
    H: float
    weight: float
    qty: int


@dataclass(frozen=True)
class PackedItem:
    item_id: str
    qty: int


@dataclass(frozen=True)
class PackedBox:
    box_type_id: str
    total_weight: float
    items: list[PackedItem] = field(default_factory=list)


@dataclass(frozen=True)
class PackingPlan:
    status: str
    reason: str
    boxes: list[PackedBox]
    metrics: dict[str, float]
