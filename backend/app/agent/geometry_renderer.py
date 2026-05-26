# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""结构化几何场景的受控 matplotlib 代码生成。"""

from __future__ import annotations

import math
from typing import Any

from app.schemas.sandbox import PythonFigureRequest


def build_geometry_figure_request(
    scene: dict[str, Any],
    operations: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    message_id: str | None = None,
) -> PythonFigureRequest:
    drawn_segments = [
        segment.get("endpoints", [])
        for segment in scene.get("observations", {}).get("drawn_segments", [])
        if isinstance(segment, dict)
    ]
    positions = _initial_positions(scene)
    if not positions:
        positions = _schematic_positions(scene, drawn_segments)
    if not positions:
        raise ValueError("cannot infer point coordinates")

    auxiliary_segments: list[list[str]] = []
    auxiliary_points: set[str] = set()

    for operation in operations:
        op_type = operation.get("type")
        params = operation.get("params", {})
        if op_type == "construct_point_on_ray_with_distance":
            new_point = str(params.get("new_point", "")).upper()
            ray = str(params.get("ray", "")).upper()
            base_point = str(params.get("base_point", "")).upper()
            distance_ref = str(params.get("distance_ref", "")).upper()
            if (
                len(ray) < 2
                or len(distance_ref) < 2
                or ray[0] not in positions
                or ray[1] not in positions
                or base_point not in positions
                or distance_ref[0] not in positions
                or distance_ref[1] not in positions
            ):
                raise ValueError("cannot infer point coordinates")
            positions[new_point] = _point_on_ray_at_distance(
                positions[base_point],
                positions[ray[1] if ray[0] == base_point else ray[0]],
                _distance(positions[distance_ref[0]], positions[distance_ref[1]]),
            )
            auxiliary_points.add(new_point)
            auxiliary_segments.append([base_point, new_point])
        elif op_type == "connect":
            points = [str(point).upper() for point in params.get("points", [])]
            if len(points) == 2:
                if points[0] not in positions or points[1] not in positions:
                    raise ValueError("cannot infer point coordinates")
                auxiliary_segments.append(points)
        elif op_type == "construct_perpendicular":
            point = str(params.get("point", "")).upper()
            line = str(params.get("line", "")).upper()
            foot = str(params.get("foot", "")).upper()
            if (
                len(line) < 2
                or point not in positions
                or line[0] not in positions
                or line[1] not in positions
                or not foot
            ):
                raise ValueError("cannot infer point coordinates")
            positions[foot] = _project_point_to_line(
                positions[point],
                positions[line[0]],
                positions[line[1]],
            )
            auxiliary_points.add(foot)
            auxiliary_segments.append([point, foot])
        elif op_type == "construct_perpendicular_intersection":
            point = str(params.get("point", "")).upper()
            line = str(params.get("line", "")).upper()
            intersect_line = str(params.get("intersect_line", "")).upper()
            foot = str(params.get("foot", "")).upper()
            if (
                len(line) < 2
                or len(intersect_line) < 2
                or point not in positions
                or line[0] not in positions
                or line[1] not in positions
                or intersect_line[0] not in positions
                or intersect_line[1] not in positions
                or not foot
            ):
                raise ValueError("cannot infer point coordinates")
            positions[foot] = _perpendicular_line_intersection(
                positions[point],
                positions[line[0]],
                positions[line[1]],
                positions[intersect_line[0]],
                positions[intersect_line[1]],
            )
            auxiliary_points.add(foot)
            auxiliary_segments.append([point, foot])
        elif op_type == "construct_parallel":
            point = str(params.get("point", "")).upper()
            line = str(params.get("line", "")).upper()
            new_line = str(params.get("new_line", "")).upper()
            if len(line) < 2 or len(new_line) < 2 or point not in positions:
                raise ValueError("cannot infer point coordinates")
            if line[0] not in positions or line[1] not in positions:
                raise ValueError("cannot infer point coordinates")
            other_point = new_line[1] if new_line[0] == point else new_line[0]
            positions[other_point] = _parallel_position(
                positions[point],
                positions[line[0]],
                positions[line[1]],
            )
            auxiliary_points.add(other_point)
            auxiliary_segments.append([point, other_point])

    code = _render_code(positions, drawn_segments, auxiliary_segments, auxiliary_points)
    return PythonFigureRequest(
        code=code,
        session_id=session_id,
        message_id=message_id,
        width=800,
        height=600,
    )


def _initial_positions(scene: dict[str, Any]) -> dict[str, tuple[float, float]]:
    points = scene.get("observations", {}).get("points", [])
    positions: dict[str, tuple[float, float]] = {}
    if not isinstance(points, list):
        return positions
    for point in points:
        if not isinstance(point, dict):
            continue
        point_id = str(point.get("id", "")).upper()
        coordinate = point.get("coordinate")
        if (
            point_id
            and isinstance(coordinate, list)
            and len(coordinate) == 2
            and all(isinstance(value, int | float) for value in coordinate)
        ):
            positions[point_id] = (float(coordinate[0]), float(coordinate[1]))
    return positions


def _schematic_positions(
    scene: dict[str, Any],
    drawn_segments: list[list[str]],
) -> dict[str, tuple[float, float]]:
    points = [
        str(point.get("id", "")).upper()
        for point in scene.get("observations", {}).get("points", [])
        if isinstance(point, dict) and point.get("id")
    ]
    if len(points) < 2:
        return {}

    positions: dict[str, tuple[float, float]] = {}
    normalized_segments = [
        [str(endpoint).upper() for endpoint in segment]
        for segment in drawn_segments
        if isinstance(segment, list) and len(segment) == 2
    ]

    if normalized_segments:
        a, b = normalized_segments[0]
        positions[a] = (0.0, 0.0)
        positions[b] = (1.0, 0.0)

    remaining = [point for point in sorted(set(points)) if point not in positions]
    radius = 1.0
    count = max(len(remaining), 1)
    for index, point in enumerate(remaining):
        angle = math.pi * (index + 1) / (count + 1)
        positions[point] = (
            0.5 + radius * math.cos(angle),
            0.8 + radius * math.sin(angle),
        )

    if len(positions) < 2:
        return {}
    return positions


def _extend_position(start: tuple[float, float], base: tuple[float, float]) -> tuple[float, float]:
    return (base[0] + (base[0] - start[0]), base[1] + (base[1] - start[1]))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _point_on_ray_at_distance(
    base: tuple[float, float],
    direction_point: tuple[float, float],
    distance: float,
) -> tuple[float, float]:
    dx = direction_point[0] - base[0]
    dy = direction_point[1] - base[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("cannot infer point coordinates")
    return (base[0] + dx / length * distance, base[1] + dy / length * distance)


def _project_point_to_line(
    point: tuple[float, float],
    line_a: tuple[float, float],
    line_b: tuple[float, float],
) -> tuple[float, float]:
    dx = line_b[0] - line_a[0]
    dy = line_b[1] - line_a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        raise ValueError("cannot infer point coordinates")
    scale = ((point[0] - line_a[0]) * dx + (point[1] - line_a[1]) * dy) / length_sq
    return (line_a[0] + scale * dx, line_a[1] + scale * dy)


def _perpendicular_line_intersection(
    point: tuple[float, float],
    line_a: tuple[float, float],
    line_b: tuple[float, float],
    target_a: tuple[float, float],
    target_b: tuple[float, float],
) -> tuple[float, float]:
    dx = line_b[0] - line_a[0]
    dy = line_b[1] - line_a[1]
    if dx == 0 and dy == 0:
        raise ValueError("cannot infer point coordinates")

    perp_dx = -dy
    perp_dy = dx
    target_dx = target_b[0] - target_a[0]
    target_dy = target_b[1] - target_a[1]
    det = perp_dx * (-target_dy) - (-target_dx) * perp_dy
    if det == 0:
        return _project_point_to_line(point, target_a, target_b)

    rhs_x = target_a[0] - point[0]
    rhs_y = target_a[1] - point[1]
    scale = (rhs_x * (-target_dy) - (-target_dx) * rhs_y) / det
    return (point[0] + scale * perp_dx, point[1] + scale * perp_dy)


def _parallel_position(
    point: tuple[float, float],
    line_a: tuple[float, float],
    line_b: tuple[float, float],
) -> tuple[float, float]:
    dx = line_b[0] - line_a[0]
    dy = line_b[1] - line_a[1]
    if dx == 0 and dy == 0:
        raise ValueError("cannot infer point coordinates")
    return (point[0] + dx, point[1] + dy)


def _render_code(
    positions: dict[str, tuple[float, float]],
    drawn_segments: list[list[str]],
    auxiliary_segments: list[list[str]],
    auxiliary_points: set[str],
) -> str:
    lines = [
        f"points = {positions!r}",
        f"drawn_segments = {drawn_segments!r}",
        f"auxiliary_segments = {auxiliary_segments!r}",
        "for a, b in drawn_segments:",
        "    if a in points and b in points:",
        "        plt.plot([points[a][0], points[b][0]], [points[a][1], points[b][1]], color='black', linewidth=1.5)",
        "for a, b in auxiliary_segments:",
        "    plt.plot([points[a][0], points[b][0]], [points[a][1], points[b][1]], color='red', linestyle='--', linewidth=1.5)",
        "for label, (x, y) in points.items():",
        f"    color = 'red' if label in {sorted(auxiliary_points)!r} else 'black'",
        "    plt.text(x, y, label, color=color, fontweight='bold', fontsize=12)",
        "plt.axis('off')",
        "plt.gca().set_aspect('equal', adjustable='box')",
    ]
    return "\n".join(lines)
