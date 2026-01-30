from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

from .types import BoxType, Item


@dataclass(frozen=True)
class FeasibilityResult:
    ok: bool
    total_weight: float
    b_min: int
    b_max: int
    reason: str


def feasibility_bounds(total_weight: float, min_weight: float, max_weight: float) -> tuple[int, int]:
    b_min = int(ceil(total_weight / max_weight)) if max_weight > 0 else 0
    b_max = int(floor(total_weight / min_weight)) if min_weight > 0 else 0
    return b_min, b_max


def check_feasibility(items: list[Item], box_type: BoxType) -> FeasibilityResult:
    total_weight = sum(item.weight * item.qty for item in items)
    b_min, b_max = feasibility_bounds(total_weight, box_type.min_weight, box_type.max_weight)
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
        )
    return FeasibilityResult(
        ok=True,
        total_weight=total_weight,
        b_min=b_min,
        b_max=b_max,
        reason="",
    )
