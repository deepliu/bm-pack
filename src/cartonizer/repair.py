from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BoxState:
    total_weight: float
    total_volume: float
    items: dict[str, int]


def _merge_boxes(target: BoxState, source: BoxState) -> None:
    target.total_weight += source.total_weight
    target.total_volume += source.total_volume
    for item_id, qty in source.items.items():
        target.items[item_id] = target.items.get(item_id, 0) + qty


def _try_merge_underweight(
    boxes: list[BoxState],
    min_weight: float,
    max_weight: float,
    max_volume: float,
) -> bool:
    under_indices = [i for i, box in enumerate(boxes) if box.total_weight < min_weight]
    if len(under_indices) < 2:
        return False

    for i in under_indices:
        best_j = None
        best_weight = -1.0
        for j in under_indices:
            if i == j:
                continue
            combined_weight = boxes[i].total_weight + boxes[j].total_weight
            combined_volume = boxes[i].total_volume + boxes[j].total_volume
            if combined_weight <= max_weight and combined_volume <= max_volume:
                if combined_weight > best_weight:
                    best_weight = combined_weight
                    best_j = j
        if best_j is not None:
            _merge_boxes(boxes[i], boxes[best_j])
            boxes.pop(best_j)
            return True
    return False


def _try_move_from_heavy(
    boxes: list[BoxState],
    item_weights: dict[str, float],
    item_volumes: dict[str, float],
    min_weight: float,
    max_weight: float,
    max_volume: float,
) -> bool:
    under_indices = [i for i, box in enumerate(boxes) if box.total_weight < min_weight]
    if not under_indices:
        return False

    donor_indices = [
        i for i, box in enumerate(boxes) if box.total_weight > min_weight
    ]
    donor_indices.sort(key=lambda i: boxes[i].total_weight, reverse=True)

    for ui in under_indices:
        under_box = boxes[ui]
        for di in donor_indices:
            if di == ui:
                continue
            donor_box = boxes[di]
            donor_items = sorted(donor_box.items.keys(), key=lambda k: item_weights[k])
            for item_id in donor_items:
                if donor_box.items.get(item_id, 0) <= 0:
                    continue
                weight = item_weights[item_id]
                volume = item_volumes[item_id]
                if under_box.total_weight + weight > max_weight:
                    continue
                if under_box.total_volume + volume > max_volume:
                    continue
                if donor_box.total_weight - weight < min_weight:
                    continue

                donor_box.items[item_id] -= 1
                if donor_box.items[item_id] == 0:
                    del donor_box.items[item_id]
                donor_box.total_weight -= weight
                donor_box.total_volume -= volume

                under_box.items[item_id] = under_box.items.get(item_id, 0) + 1
                under_box.total_weight += weight
                under_box.total_volume += volume
                return True
    return False


def _try_swap(
    boxes: list[BoxState],
    item_weights: dict[str, float],
    item_volumes: dict[str, float],
    min_weight: float,
    max_weight: float,
    max_volume: float,
) -> bool:
    under_indices = [i for i, box in enumerate(boxes) if box.total_weight < min_weight]
    if not under_indices:
        return False

    for ui in under_indices:
        under_box = boxes[ui]
        for di, donor_box in enumerate(boxes):
            if di == ui:
                continue
            for under_item_id in list(under_box.items.keys()):
                if under_box.items.get(under_item_id, 0) <= 0:
                    continue
                w_u = item_weights[under_item_id]
                v_u = item_volumes[under_item_id]
                for donor_item_id in list(donor_box.items.keys()):
                    if donor_box.items.get(donor_item_id, 0) <= 0:
                        continue
                    w_d = item_weights[donor_item_id]
                    v_d = item_volumes[donor_item_id]

                    new_under_weight = under_box.total_weight - w_u + w_d
                    new_donor_weight = donor_box.total_weight - w_d + w_u
                    if not (min_weight <= new_under_weight <= max_weight):
                        continue
                    if not (min_weight <= new_donor_weight <= max_weight):
                        continue

                    new_under_volume = under_box.total_volume - v_u + v_d
                    new_donor_volume = donor_box.total_volume - v_d + v_u
                    if new_under_volume > max_volume or new_donor_volume > max_volume:
                        continue

                    under_box.items[under_item_id] -= 1
                    if under_box.items[under_item_id] == 0:
                        del under_box.items[under_item_id]
                    donor_box.items[donor_item_id] -= 1
                    if donor_box.items[donor_item_id] == 0:
                        del donor_box.items[donor_item_id]

                    under_box.items[donor_item_id] = under_box.items.get(donor_item_id, 0) + 1
                    donor_box.items[under_item_id] = donor_box.items.get(under_item_id, 0) + 1

                    under_box.total_weight = new_under_weight
                    donor_box.total_weight = new_donor_weight
                    under_box.total_volume = new_under_volume
                    donor_box.total_volume = new_donor_volume
                    return True
    return False


def repair_underweight(
    boxes: list[BoxState],
    item_weights: dict[str, float],
    item_volumes: dict[str, float],
    min_weight: float,
    max_weight: float,
    max_volume: float,
) -> list[BoxState]:
    if not boxes:
        return boxes

    max_iter = max(10, len(boxes) * 10)
    for _ in range(max_iter):
        under = [box for box in boxes if box.total_weight < min_weight]
        if not under:
            break
        if _try_merge_underweight(boxes, min_weight, max_weight, max_volume):
            continue
        if _try_move_from_heavy(
            boxes,
            item_weights,
            item_volumes,
            min_weight,
            max_weight,
            max_volume,
        ):
            continue
        if _try_swap(
            boxes,
            item_weights,
            item_volumes,
            min_weight,
            max_weight,
            max_volume,
        ):
            continue
        break
    return boxes
