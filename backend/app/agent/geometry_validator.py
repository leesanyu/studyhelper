# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""校验辅助操作是否可追溯、可引用、可渲染。"""

from __future__ import annotations

from typing import Any

from app.agent.geometry_types import CONSTRUCTION_TYPES


def validate_geometry_operations(
    scene: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    known_points = _scene_points(scene)
    constructed_counts = _constructed_point_counts(operations)
    rejected: list[dict[str, str]] = []
    accepted: list[dict[str, Any]] = []

    available_points = set(known_points)
    for operation in operations:
        reason = _reject_reason(operation, available_points, constructed_counts)
        if reason:
            rejected.append({
                "operation_id": str(operation.get("id", "")),
                "reason": reason,
            })
        else:
            accepted.append(operation)
            new_point = _constructed_point(operation)
            if new_point and constructed_counts.get(new_point) == 1:
                available_points.add(new_point)

    ok = not rejected
    warnings = _visual_review_warnings(scene, operations) if ok else []
    return {
        "ok": ok,
        "code": "" if ok else "geometry_check_failed",
        "message": "" if ok else "辅助线校验失败",
        "accepted_operations": accepted if ok else [],
        "rejected_operations": rejected,
        "warnings": warnings,
        "needs_visual_review": bool(warnings),
    }


def _scene_points(scene: dict[str, Any]) -> set[str]:
    observations = scene.get("observations", {})
    points = observations.get("points", []) if isinstance(observations, dict) else []
    return {
        str(point.get("id", "")).upper()
        for point in points
        if isinstance(point, dict) and point.get("id")
    }


def _constructed_point_counts(operations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations:
        if operation.get("type") not in CONSTRUCTION_TYPES:
            continue
        new_point = operation.get("params", {}).get("new_point") or operation.get("params", {}).get("foot")
        if new_point:
            key = str(new_point).upper()
            counts[key] = counts.get(key, 0) + 1
    return counts


def _constructed_point(operation: dict[str, Any]) -> str | None:
    if operation.get("type") not in CONSTRUCTION_TYPES:
        return None
    params = operation.get("params", {})
    new_point = params.get("new_point") or params.get("foot")
    if not new_point:
        return None
    return str(new_point).upper()


def _reject_reason(
    operation: dict[str, Any],
    available_points: set[str],
    constructed_counts: dict[str, int],
) -> str | None:
    if not operation.get("source_sentence"):
        return "missing source_sentence"

    params = operation.get("params", {})
    op_type = operation.get("type")

    for point, count in constructed_counts.items():
        if count > 1:
            return f"duplicate construction for new point {point}"

    for point in _referenced_existing_points(op_type, params):
        if point not in available_points:
            return f"unknown point {point}"

    if op_type == "connect":
        for point in params.get("points", []):
            if str(point).upper() not in available_points:
                return f"unknown point {str(point).upper()}"

    return None


def _referenced_existing_points(op_type: str, params: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    if op_type == "construct_point_on_ray_with_distance":
        refs.extend(_segment_points(params.get("ray")))
        refs.extend(_segment_points(params.get("distance_ref")))
        refs.append(str(params.get("base_point", "")).upper())
    elif op_type == "extend_line":
        refs.extend(_segment_points(params.get("line")))
        refs.append(str(params.get("through", "")).upper())
    elif op_type == "extend_ray":
        refs.extend(_segment_points(params.get("ray")))
    elif op_type == "intersection":
        refs.extend(_segment_points(params.get("a")))
        refs.extend(_segment_points(params.get("b")))
    elif op_type == "midpoint":
        refs.extend(_segment_points(params.get("segment")))
    elif op_type == "construct_perpendicular":
        refs.append(str(params.get("point", "")).upper())
        refs.extend(_segment_points(params.get("line")))
    elif op_type == "construct_perpendicular_intersection":
        refs.append(str(params.get("point", "")).upper())
        refs.extend(_segment_points(params.get("line")))
        refs.extend(_segment_points(params.get("intersect_line")))
    elif op_type == "construct_parallel":
        refs.append(str(params.get("point", "")).upper())
        refs.extend(_segment_points(params.get("line")))
    return [point for point in refs if point]


def _segment_points(segment: Any) -> list[str]:
    if not isinstance(segment, str):
        return []
    value = segment.upper()
    if len(value) < 2:
        return []
    return [value[0], value[1]]


def _visual_review_warnings(
    scene: dict[str, Any],
    operations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    uncertain_items = scene.get("uncertain", [])
    if not isinstance(uncertain_items, list) or not uncertain_items:
        return []
    directional_ops = {
        "extend_line",
        "extend_ray",
        "construct_point_on_ray_with_distance",
        "copy_segment_on_ray",
    }
    if not any(operation.get("type") in directional_ops for operation in operations):
        return []
    return [{
        "code": "visual_review_recommended",
        "message": "存在低置信度点序或方向信息，建议进行视觉复核",
    }]
