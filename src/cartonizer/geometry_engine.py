from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geometry import GeometryResult, geometry_validate
from .types import BoxType, Item, PackedBox, PackedItem


@dataclass(frozen=True)
class GeometryEngine:
    items_by_id: dict[str, Item]
    enabled: bool = False
    allow_rotation: bool = False
    visualize_dir: Optional[str] = None

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
        return geometry_validate(
            packed_box,
            box_type,
            self.items_by_id,
            visualize_path=visualize_path,
            allow_rotation=self.allow_rotation,
        )

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
