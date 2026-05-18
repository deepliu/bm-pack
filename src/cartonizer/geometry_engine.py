from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .geometry import GeometryResult, geometry_validate
from .types import BoxType, Item, PackedBox, PackedItem


@dataclass(frozen=True)
class GeometryEngine:
    items_by_id: dict[str, Item]
    enabled: bool = False
    allow_rotation: bool = False
    visualize_dir: Optional[str] = None
    _cache: dict[tuple[object, ...], GeometryResult] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _cache_hits: int = field(default=0, init=False, repr=False, compare=False)
    _cache_misses: int = field(default=0, init=False, repr=False, compare=False)

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses

    def _cache_key(
        self,
        packed_box: PackedBox,
        box_type: BoxType,
    ) -> tuple[object, ...]:
        return (
            self.allow_rotation,
            box_type.id,
            box_type.inner_L,
            box_type.inner_W,
            box_type.inner_H,
            tuple(sorted((item.item_id, item.qty) for item in packed_box.items)),
        )

    def validate_box(
        self,
        packed_box: PackedBox,
        box_type: BoxType,
        *,
        sequence: int | None = None,
        visualize: bool = True,
    ) -> GeometryResult:
        if not self.enabled:
            return GeometryResult(ok=True, reason="", unfit_count=0)

        visualize_path = None
        if visualize and self.visualize_dir and sequence is not None:
            from pathlib import Path

            visualize_path = str(
                Path(self.visualize_dir) / f"{packed_box.box_type_id}_box_{sequence}.png"
            )
        cache_key = self._cache_key(packed_box, box_type)
        if visualize_path is None and cache_key in self._cache:
            object.__setattr__(self, "_cache_hits", self._cache_hits + 1)
            return self._cache[cache_key]

        result = geometry_validate(
            packed_box,
            box_type,
            self.items_by_id,
            visualize_path=visualize_path,
            allow_rotation=self.allow_rotation,
        )
        if visualize_path is None:
            self._cache[cache_key] = result
            object.__setattr__(self, "_cache_misses", self._cache_misses + 1)
        return result

    def can_place_items(
        self,
        box_type: BoxType,
        item_quantities: dict[str, int],
    ) -> bool:
        packed_box = PackedBox(
            box_type_id=box_type.id,
            total_weight=sum(
                self.items_by_id[item_id].weight * qty
                for item_id, qty in item_quantities.items()
            )
            + box_type.tare_weight,
            items=[
                PackedItem(item_id=item_id, qty=qty)
                for item_id, qty in item_quantities.items()
                if qty > 0
            ],
        )
        return self.validate_box(packed_box, box_type).ok

    def validate_plan(
        self,
        boxes: list[PackedBox],
        box_types_by_id: dict[str, BoxType],
        *,
        visualize: bool = True,
    ) -> tuple[bool, str]:
        for idx, packed_box in enumerate(boxes, start=1):
            result = self.validate_box(
                packed_box,
                box_types_by_id[packed_box.box_type_id],
                sequence=idx,
                visualize=visualize,
            )
            if not result.ok:
                return False, result.reason
        return True, ""
