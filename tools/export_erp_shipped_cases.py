from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ERP_ROOT = Path(r"D:\fu\Himool\erp")
DEFAULT_ERP_PYTHON = DEFAULT_ERP_ROOT / "venv" / "Scripts" / "python.exe"
DEFAULT_OUTPUT = PROJECT_ROOT / "examples" / "erp_shipped_manual_cases.json"
DEFAULT_MIN_MANUAL_BOX_WEIGHT = 12.0
DEFAULT_MAX_MANUAL_BOX_SKU_TYPES = 6
DEFAULT_MIN_MANUAL_BOX_COUNT = 2
DEFAULT_SCAN_LIMIT = 300


def _decimal_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _setup_django(erp_root: Path, settings_module: str) -> None:
    sys.path.insert(0, str(erp_root))
    os.chdir(erp_root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    import django

    django.setup()


def _maybe_reexec_with_erp_python(erp_python: Path) -> int | None:
    if importlib.util.find_spec("django") is not None:
        return None
    current = Path(sys.executable).resolve()
    target = erp_python.resolve()
    if current == target:
        return None
    if not target.exists():
        raise RuntimeError(f"Django is not installed and ERP python was not found: {target}")
    return subprocess.run(
        [str(target), str(Path(__file__).resolve()), *sys.argv[1:]],
        check=False,
    ).returncode


def _manual_boxes(plan) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in plan.items.all().order_by("carton_no", "id"):
        carton_no = str(row.carton_no)
        box = grouped.setdefault(
            carton_no,
            {
                "carton_no": carton_no,
                "box_type": row.box_type or "",
                "total_weight": _decimal_to_float(row.actual_weight or row.gross_weight_kg),
                "items": [],
            },
        )
        if not box["box_type"] and row.box_type:
            box["box_type"] = row.box_type
        box["total_weight"] = max(
            _decimal_to_float(row.actual_weight or row.gross_weight_kg),
            box["total_weight"],
        )
        box["items"].append(
            {
                "sku": row.sku,
                "goods_id": str(row.goods_id or ""),
                "qty": int(row.qty or 0),
            }
        )
    return list(grouped.values())


def _quantity_summary(boxes: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = defaultdict(int)
    for box in boxes:
        for item in box.get("items", []):
            key = item.get("goods_id") or item.get("sku") or ""
            if not key:
                continue
            summary[str(key)] += int(item.get("qty") or 0)
    return dict(summary)


def _case_exclusion_reason(
    payload: dict[str, Any],
    *,
    min_manual_box_weight: float,
    max_manual_box_sku_types: int,
    min_manual_box_count: int,
) -> dict[str, Any] | None:
    low_weight_boxes = []
    over_sku_boxes = []
    manual_boxes = payload.get("manual_boxes") or []
    for box in payload.get("manual_boxes") or []:
        total_weight = float(box.get("total_weight") or 0)
        sku_type_count = len(
            [
                item
                for item in box.get("items", [])
                if int(item.get("qty") or 0) > 0
            ]
        )
        if total_weight < min_manual_box_weight:
            low_weight_boxes.append(
                {
                    "carton_no": box.get("carton_no"),
                    "total_weight": total_weight,
                }
            )
        if sku_type_count > max_manual_box_sku_types:
            over_sku_boxes.append(
                {
                    "carton_no": box.get("carton_no"),
                    "sku_type_count": sku_type_count,
                }
            )
    too_few_boxes = len(manual_boxes) < min_manual_box_count
    if not low_weight_boxes and not over_sku_boxes and not too_few_boxes:
        return None
    return {
        "carton_plan_id": payload.get("carton_plan_id"),
        "store_name": payload.get("store_name"),
        "handle_date": payload.get("handle_date"),
        "manual_box_count": len(manual_boxes),
        "min_manual_box_count": min_manual_box_count if too_few_boxes else None,
        "low_weight_boxes": low_weight_boxes,
        "over_sku_type_boxes": over_sku_boxes,
    }


def _case_payload(plan, carton_service) -> dict[str, Any] | None:
    shipment = getattr(plan, "shipment", None)
    if shipment is None:
        return None
    production_orders = [
        order.production_order
        for order in shipment.orders.all()
        if getattr(order, "production_order", None) is not None
    ]
    if not production_orders:
        return None

    goods_ids = [
        str(getattr(order, "goods_id", "") or "")
        for order in production_orders
        if getattr(order, "goods_id", None)
    ]
    packing_box_map = carton_service._packing_box_dimension_map(goods_ids)
    item_rows = carton_service._cartonizer_item_rows_from_orders(
        production_orders,
        packing_box_map,
    )
    box_type_rows = carton_service._cartonizer_box_type_rows()
    manual_boxes = _manual_boxes(plan)
    return {
        "carton_plan_id": plan.id,
        "store_name": plan.store_name,
        "handle_date": str(plan.handle_date),
        "number": plan.number,
        "source_type": plan.source_type,
        "box_types": box_type_rows,
        "items": item_rows,
        "manual_boxes": manual_boxes,
        "manual_metrics": {
            "box_count": len(manual_boxes),
            "total_qty": sum(_quantity_summary(manual_boxes).values()),
            "quantity_summary": _quantity_summary(manual_boxes),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export shipped ERP manual carton plans as bm-pack regression fixtures."
    )
    parser.add_argument(
        "--erp-root",
        default=str(DEFAULT_ERP_ROOT),
        help="Path to the ERP project root",
    )
    parser.add_argument(
        "--erp-python",
        default=str(DEFAULT_ERP_PYTHON),
        help="ERP virtualenv python used when current python cannot import Django",
    )
    parser.add_argument(
        "--settings",
        default="project.settings",
        help="Django settings module for ERP",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output JSON path",
    )
    parser.add_argument("--limit", type=int, default=30, help="Accepted case count")
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=DEFAULT_SCAN_LIMIT,
        help="Maximum shipped carton plans to scan before filtering",
    )
    parser.add_argument(
        "--min-manual-box-weight",
        type=float,
        default=DEFAULT_MIN_MANUAL_BOX_WEIGHT,
    )
    parser.add_argument(
        "--max-manual-box-sku-types",
        type=int,
        default=DEFAULT_MAX_MANUAL_BOX_SKU_TYPES,
    )
    parser.add_argument(
        "--min-manual-box-count",
        type=int,
        default=DEFAULT_MIN_MANUAL_BOX_COUNT,
    )
    parser.add_argument("--store-name", default="")
    parser.add_argument("--handle-date", default="")
    args = parser.parse_args()

    erp_root = Path(args.erp_root).resolve()
    reexec_code = _maybe_reexec_with_erp_python(Path(args.erp_python))
    if reexec_code is not None:
        return reexec_code
    _setup_django(erp_root, args.settings)

    from apps.carton.models import CartonPlan
    from apps.carton.services import CartonPlanService

    qs = (
        CartonPlan.objects.filter(status=CartonPlan.Status.SHIPPED)
        .prefetch_related("items", "shipment__orders__production_order__goods")
        .order_by("-id")
    )
    if args.store_name:
        qs = qs.filter(store_name=args.store_name)
    if args.handle_date:
        qs = qs.filter(handle_date=args.handle_date)

    cases = []
    excluded = []
    scanned = 0
    for plan in qs[: args.scan_limit]:
        if len(cases) >= args.limit:
            break
        scanned += 1
        payload = _case_payload(plan, CartonPlanService)
        if not payload:
            continue
        reason = _case_exclusion_reason(
            payload,
            min_manual_box_weight=args.min_manual_box_weight,
            max_manual_box_sku_types=args.max_manual_box_sku_types,
            min_manual_box_count=args.min_manual_box_count,
        )
        if reason:
            excluded.append(reason)
            continue
        cases.append(payload)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "filters": {
                    "min_manual_box_weight": args.min_manual_box_weight,
                    "max_manual_box_sku_types": args.max_manual_box_sku_types,
                    "min_manual_box_count": args.min_manual_box_count,
                    "accepted_limit": args.limit,
                    "scan_limit": args.scan_limit,
                    "scanned_count": scanned,
                    "excluded_count": len(excluded),
                    "excluded_cases": excluded,
                },
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"exported {len(cases)} cases to {output_path}; "
        f"scanned={scanned}, excluded={len(excluded)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
