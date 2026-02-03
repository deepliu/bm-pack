from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .types import BoxType, PackedBox, PackedItem, Item


@dataclass(frozen=True)
class GeometryResult:
    ok: bool
    reason: str
    unfit_count: int


def _import_py3dbp():
    try:
        from py3dbp import Bin, Item, Packer  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("py3dbp is required for geometry validation") from exc

    try:
        from py3dbp import Painter  # type: ignore
    except Exception:  # pragma: no cover - optional
        Painter = None

    return Bin, Item, Packer, Painter


def _build_bin(bin_cls: Any, box_type: BoxType):
    params = bin_cls.__init__.__code__.co_varnames
    if "width" in params and "height" in params and "depth" in params:
        return bin_cls(
            box_type.id,
            box_type.inner_L,
            box_type.inner_W,
            box_type.inner_H,
            box_type.max_weight,
        )
    if "WHL" in params or "WHD" in params or "WHD" in params:
        return bin_cls(
            box_type.id,
            (box_type.inner_L, box_type.inner_W, box_type.inner_H),
            box_type.max_weight,
        )
    return bin_cls(
        box_type.id,
        (box_type.inner_L, box_type.inner_W, box_type.inner_H),
        box_type.max_weight,
    )


def _build_item(item_cls: Any, item: Item):
    params = item_cls.__init__.__code__.co_varnames
    dims = (item.L, item.W, item.H)
    if "width" in params and "height" in params and "depth" in params:
        return item_cls(item.id, item.L, item.W, item.H, item.weight)
    if "typeof" in params:
        return item_cls(
            item.id,
            item.id,
            "cube",
            dims,
            item.weight,
            1,
            100,
            True,
            "gray",
        )
    return item_cls(item.id, dims, item.weight)


def _iter_items(packed_items: Iterable[PackedItem], items_by_id: dict[str, Item]) -> list[Item]:
    expanded: list[Item] = []
    for packed in packed_items:
        item = items_by_id[packed.item_id]
        for _ in range(packed.qty):
            expanded.append(
                Item(
                    id=item.id,
                    L=item.L,
                    W=item.W,
                    H=item.H,
                    weight=item.weight,
                    qty=1,
                )
            )
    return expanded


def _save_figure(fig: Any, output_path: Path) -> None:
    if output_path.suffix.lower() == ".html" and hasattr(fig, "write_html"):
        fig.write_html(str(output_path))
        return
    if hasattr(fig, "write_image"):
        fig.write_image(str(output_path))
        return
    if hasattr(fig, "savefig"):
        fig.savefig(str(output_path))
        return


def _plot_matplotlib(bin_obj: Any, output_path: Path) -> None:
    from matplotlib import pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection="3d")

    max_x = float(bin_obj.width)
    max_y = float(bin_obj.height)
    max_z = float(bin_obj.depth)
    ax.set_xlim(0, max_x)
    ax.set_ylim(0, max_y)
    ax.set_zlim(0, max_z)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")

    colors = [
        "#5DA5DA",
        "#F15854",
        "#DECF3F",
        "#B276B2",
        "#FAA43A",
        "#60BD68",
        "#F17CB0",
    ]

    def _cuboid_faces(x: float, y: float, z: float, dx: float, dy: float, dz: float):
        return [
            [(x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z)],
            [(x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)],
            [(x, y, z), (x + dx, y, z), (x + dx, y, z + dz), (x, y, z + dz)],
            [(x, y + dy, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)],
            [(x, y, z), (x, y + dy, z), (x, y + dy, z + dz), (x, y, z + dz)],
            [(x + dx, y, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz), (x + dx, y, z + dz)],
        ]

    for idx, item in enumerate(getattr(bin_obj, "items", [])):
        pos = getattr(item, "position", [0, 0, 0])
        dims = item.get_dimension()
        x, y, z = (float(pos[0]), float(pos[1]), float(pos[2]))
        dx, dy, dz = (float(dims[0]), float(dims[1]), float(dims[2]))
        faces = _cuboid_faces(x, y, z, dx, dy, dz)
        poly = Poly3DCollection(
            faces,
            facecolors=colors[idx % len(colors)],
            linewidths=0.4,
            edgecolors="#333333",
            alpha=0.7,
        )
        ax.add_collection3d(poly)

    fig.tight_layout()
    fig.savefig(str(output_path))
    plt.close(fig)


def geometry_validate(
    packed_box: PackedBox,
    box_type: BoxType,
    items_by_id: dict[str, Item],
    *,
    visualize_path: str | None = None,
) -> GeometryResult:
    Bin, ItemCls, Packer, Painter = _import_py3dbp()

    packer = Packer()
    bin_obj = _build_bin(Bin, box_type)
    packer.add_bin(bin_obj)

    for item in _iter_items(packed_box.items, items_by_id):
        packer.add_item(_build_item(ItemCls, item))

    pack_kwargs = {
        "bigger_first": True,
        "distribute_items": False,
        "number_of_decimals": 3,
    }
    try:
        import inspect

        supported = set(inspect.signature(packer.pack).parameters.keys())
        packer.pack(**{k: v for k, v in pack_kwargs.items() if k in supported})
    except Exception:
        packer.pack(**pack_kwargs)

    unfit_count = len(getattr(packer, "unfit_items", []))
    if unfit_count:
        return GeometryResult(
            ok=False,
            reason="geometry infeasible: unfit items",
            unfit_count=unfit_count,
        )

    if visualize_path:
        output_path = Path(visualize_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if Painter is not None:
            painter = Painter(bin_obj)  # type: ignore[call-arg]
            fig = painter.plotBoxAndItems(  # type: ignore[attr-defined]
                title=packed_box.box_type_id,
                axis=True,
                first=True,
            )
            _save_figure(fig, output_path)
        else:
            _plot_matplotlib(bin_obj, output_path)

    return GeometryResult(ok=True, reason="", unfit_count=0)
