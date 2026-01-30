from __future__ import annotations

from math import ceil

from .feasibility import check_feasibility
from .types import BoxType, Item, PackingPlan


def solve(items: list[Item], box_type: BoxType) -> PackingPlan:
    feasibility = check_feasibility(items, box_type)
    total_weight = feasibility.total_weight
    if not feasibility.ok:
        return PackingPlan(
            status="infeasible",
            reason=feasibility.reason,
            boxes=[],
            metrics={
                "total_weight": total_weight,
                "box_count": 0.0,
                "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
            },
        )

    return PackingPlan(
        status="ok",
        reason="",
        boxes=[],
        metrics={
            "total_weight": total_weight,
            "box_count": 0.0,
            "lower_bound_by_weight": float(ceil(total_weight / box_type.max_weight)),
        },
    )
