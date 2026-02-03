from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor

from .types import BoxType, Item


@dataclass(frozen=True)
class FeasibilityResult:
    ok: bool
    total_weight: float
    b_min: int
    b_max: int
    reason: str
    suggestions: list[dict[str, object]] = field(default_factory=list)


def _build_suggestions(
    items: list[Item],
    *,
    total_weight: float,
    min_weight: float,
    max_weight: float,
    b_min: int,
    b_max: int,
    max_options: int = 3,
) -> list[dict[str, object]]:
    if not items:
        return []

    suggestions: list[dict[str, object]] = []

    if b_max > 0:
        target = max_weight * b_max
        if total_weight > target:
            delta = total_weight - target
            options = []
            for item in items:
                if item.weight <= 0:
                    continue
                qty = int(ceil(delta / item.weight))
                options.append(
                    {
                        "item_id": item.id,
                        "unit_weight": item.weight,
                        "qty_change": -qty,
                        "weight_change": -qty * item.weight,
                    }
                )
            options.sort(key=lambda o: abs(int(o["qty_change"])))
            suggestions.append(
                {
                    "action": "reduce",
                    "target_total_weight": target,
                    "delta_weight": -delta,
                    "recommended_box_count": b_max,
                    "options": options[:max_options],
                }
            )

    if b_min > 0:
        target = min_weight * b_min
        if total_weight < target:
            delta = target - total_weight
            options = []
            for item in items:
                if item.weight <= 0:
                    continue
                qty = int(ceil(delta / item.weight))
                options.append(
                    {
                        "item_id": item.id,
                        "unit_weight": item.weight,
                        "qty_change": qty,
                        "weight_change": qty * item.weight,
                    }
                )
            options.sort(key=lambda o: abs(int(o["qty_change"])))
            suggestions.append(
                {
                    "action": "increase",
                    "target_total_weight": target,
                    "delta_weight": delta,
                    "recommended_box_count": b_min,
                    "options": options[:max_options],
                }
            )

    return suggestions


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
            suggestions=_build_suggestions(
                items,
                total_weight=total_weight,
                min_weight=box_type.min_weight,
                max_weight=box_type.max_weight,
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
