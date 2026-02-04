from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BoxState:
    box_type_id: str
    min_weight: float
    max_weight: float
    tare_weight: float
    box_volume: float
    max_volume: float
    total_weight: float
    total_volume: float
    items: dict[str, int]


def _merge_boxes(target: BoxState, source: BoxState) -> None:
    # Remove source box tare because boxes are merged into a single box.
    target.total_weight += source.total_weight - source.tare_weight
    target.total_volume += source.total_volume
    for item_id, qty in source.items.items():
        target.items[item_id] = target.items.get(item_id, 0) + qty


def _try_merge_underweight(
    boxes: list[BoxState],
) -> bool:
    under_indices = [i for i, box in enumerate(boxes) if box.total_weight < box.min_weight]
    if len(under_indices) < 2:
        return False

    def _try_merge(prefer_same_sku: bool) -> bool:
        for i in under_indices:
            best_j = None
            best_weight = -1.0
            sku_i = set(boxes[i].items.keys())
            for j in under_indices:
                if i == j:
                    continue
                if prefer_same_sku and sku_i != set(boxes[j].items.keys()):
                    continue
                combined_weight = (
                    boxes[i].total_weight + boxes[j].total_weight - boxes[j].tare_weight
                )
                combined_volume = boxes[i].total_volume + boxes[j].total_volume
                if combined_weight <= boxes[i].max_weight and combined_volume <= boxes[i].max_volume:
                    if combined_weight > best_weight:
                        best_weight = combined_weight
                        best_j = j
            if best_j is not None:
                _merge_boxes(boxes[i], boxes[best_j])
                boxes.pop(best_j)
                return True
        return False

    if _try_merge(prefer_same_sku=True):
        return True
    if _try_merge(prefer_same_sku=False):
        return True
    return False


def _try_move_from_heavy(
    boxes: list[BoxState],
    item_weights: dict[str, float],
    item_volumes: dict[str, float],
) -> bool:
    under_indices = [i for i, box in enumerate(boxes) if box.total_weight < box.min_weight]
    if not under_indices:
        return False

    donor_indices = [
        i for i, box in enumerate(boxes) if box.total_weight > box.min_weight
    ]
    donor_indices.sort(key=lambda i: boxes[i].total_weight, reverse=True)

    def _try_move(prefer_same_sku: bool) -> bool:
        for ui in under_indices:
            under_box = boxes[ui]
            under_skus = set(under_box.items.keys())
            for di in donor_indices:
                if di == ui:
                    continue
                donor_box = boxes[di]
                donor_items = sorted(donor_box.items.keys(), key=lambda k: item_weights[k])
                for item_id in donor_items:
                    if prefer_same_sku and item_id not in under_skus:
                        continue
                    if donor_box.items.get(item_id, 0) <= 0:
                        continue
                    weight = item_weights[item_id]
                    volume = item_volumes[item_id]
                    if under_box.total_weight + weight > under_box.max_weight:
                        continue
                    if under_box.total_volume + volume > under_box.max_volume:
                        continue
                    if donor_box.total_weight - weight < donor_box.min_weight:
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

    if _try_move(prefer_same_sku=True):
        return True
    if _try_move(prefer_same_sku=False):
        return True
    return False


def _try_swap(
    boxes: list[BoxState],
    item_weights: dict[str, float],
    item_volumes: dict[str, float],
) -> bool:
    under_indices = [i for i, box in enumerate(boxes) if box.total_weight < box.min_weight]
    if not under_indices:
        return False

    def _try_swap(prefer_same_sku: bool) -> bool:
        for ui in under_indices:
            under_box = boxes[ui]
            under_skus = set(under_box.items.keys())
            for di, donor_box in enumerate(boxes):
                if di == ui:
                    continue
                for under_item_id in list(under_box.items.keys()):
                    if under_box.items.get(under_item_id, 0) <= 0:
                        continue
                    w_u = item_weights[under_item_id]
                    v_u = item_volumes[under_item_id]
                    for donor_item_id in list(donor_box.items.keys()):
                        if prefer_same_sku and donor_item_id not in under_skus:
                            continue
                        if donor_box.items.get(donor_item_id, 0) <= 0:
                            continue
                        w_d = item_weights[donor_item_id]
                        v_d = item_volumes[donor_item_id]

                        new_under_weight = under_box.total_weight - w_u + w_d
                        new_donor_weight = donor_box.total_weight - w_d + w_u
                        if not (under_box.min_weight <= new_under_weight <= under_box.max_weight):
                            continue
                        if not (donor_box.min_weight <= new_donor_weight <= donor_box.max_weight):
                            continue

                        new_under_volume = under_box.total_volume - v_u + v_d
                        new_donor_volume = donor_box.total_volume - v_d + v_u
                        if new_under_volume > under_box.max_volume or new_donor_volume > donor_box.max_volume:
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

    if _try_swap(prefer_same_sku=True):
        return True
    if _try_swap(prefer_same_sku=False):
        return True
    return False


def repair_underweight(
    boxes: list[BoxState],
    item_weights: dict[str, float],
    item_volumes: dict[str, float],
) -> list[BoxState]:
    if not boxes:
        return boxes

    max_iter = max(10, len(boxes) * 10)
    for _ in range(max_iter):
        under = [box for box in boxes if box.total_weight < box.min_weight]
        if not under:
            break
        if _try_merge_underweight(boxes):
            continue
        if _try_move_from_heavy(
            boxes,
            item_weights,
            item_volumes,
        ):
            continue
        if _try_swap(
            boxes,
            item_weights,
            item_volumes,
        ):
            continue
        break
    return boxes
