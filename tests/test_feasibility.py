from cartonizer.feasibility import check_feasibility
from cartonizer.types import BoxType, Item


def test_feasible_bounds():
    box = BoxType(id="A", inner_L=10, inner_W=10, inner_H=10)
    items = [Item(id="sku1", L=1, W=1, H=1, weight=10.0, qty=2)]
    result = check_feasibility(items, box)
    assert result.ok
    assert result.b_min == 1
    assert result.b_max == 1


def test_infeasible_bounds():
    box = BoxType(id="A", inner_L=10, inner_W=10, inner_H=10)
    items = [Item(id="sku1", L=1, W=1, H=1, weight=5.0, qty=2)]
    result = check_feasibility(items, box)
    assert not result.ok
    assert result.b_min == 1
    assert result.b_max == 0
