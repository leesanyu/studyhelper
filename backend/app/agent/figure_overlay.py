# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""原图 overlay 绘图工具。

该模块只负责图像裁剪、坐标计算、叠加渲染和资产落盘，不决定辅助线策略。
"""

from __future__ import annotations

import io
import math
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.services.assets import AssetCreate, AssetRepository
from app.services.storage import AssetStorage


class OverlayRenderError(ValueError):
    """overlay 渲染失败，携带可交给 LLM 的 Observation。"""

    def __init__(self, message: str, *, observation: dict[str, Any]) -> None:
        super().__init__(message)
        self.observation = observation


Point = tuple[float, float]

_AUXILIARY_LINE_WIDTH = 4
_HIGHLIGHT_LINE_WIDTH = 5


async def crop_target_diagram(
    *,
    image_path: str | Path,
    crop_box: list[int | float] | tuple[int | float, int | float, int | float, int | float] | None,
    asset_repository: AssetRepository | None = None,
    storage: AssetStorage | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    label: str = "",
    display_scale: int = 2,
) -> dict[str, Any]:
    """截取目标几何图，并可选保存裁剪图资产。"""
    started_at = time.monotonic()
    source_path = Path(image_path)
    image = Image.open(source_path).convert("RGB")
    width, height = image.size
    box = _normalize_crop_box(crop_box, width=width, height=height)
    crop = image.crop(box)

    asset_id = str(uuid4())
    png_content = _image_to_png(crop)
    image_url = f"/assets/{asset_id}.png"
    object_key = ""
    if asset_repository is not None and storage is not None:
        stored = await storage.save(
            asset_id=asset_id,
            content=png_content,
            extension=".png",
            prefix="figures",
        )
        image_url = stored["url"]
        object_key = stored["object_key"]
        await asset_repository.create_asset(
            AssetCreate(
                asset_id=asset_id,
                asset_type="figure_target_crop",
                storage_backend=stored["storage_backend"],
                object_key=stored["object_key"],
                url=stored["url"],
                filename=f"{asset_id}.png",
                mime_type="image/png",
                size_bytes=len(png_content),
                width=crop.width,
                height=crop.height,
                session_id=session_id,
                message_id=message_id,
                metadata={
                    "label": label,
                    "crop_box": list(box),
                    "coordinate_space": "crop_pixels",
                    "display_scale": display_scale,
                },
            )
        )

    return {
        "label": label,
        "crop_asset_id": asset_id,
        "crop_box": list(box),
        "crop_path": str(Path(storage._root_dir) / object_key) if object_key and hasattr(storage, "_root_dir") else "",
        "image_url": image_url,
        "width": crop.width,
        "height": crop.height,
        "coordinate_space": "crop_pixels",
        "display_scale": display_scale,
        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
        "warnings": [],
    }


async def render_overlay_plan(
    *,
    image_path: str | Path,
    overlay_plan: dict[str, Any],
    localized_points: dict[str, Any],
    asset_repository: AssetRepository | None = None,
    storage: AssetStorage | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    display_scale: int = 2,
) -> dict[str, Any]:
    """按 overlay plan 在裁剪图上绘制辅助线。"""
    started_at = time.monotonic()
    if display_scale < 1:
        display_scale = 1

    image = Image.open(Path(image_path)).convert("RGBA")
    if display_scale != 1:
        image = image.resize(
            (image.width * display_scale, image.height * display_scale),
            Image.Resampling.LANCZOS,
        )

    draw = ImageDraw.Draw(image)
    font = _load_font(size=max(20, 18 * display_scale))
    points = _normalize_points(localized_points, display_scale=display_scale)
    computed_points: dict[str, dict[str, float]] = {}
    warnings: list[str] = []

    constructions = overlay_plan.get("constructions")
    if not isinstance(constructions, list):
        raise _overlay_error("overlay plan missing constructions")

    supported_operation_count = 0
    for item in constructions:
        if not isinstance(item, dict):
            warnings.append("invalid_operation")
            continue
        op = str(item.get("op") or "")
        if op == "point_on_segment_by_distance":
            point_name, point = _construct_point_on_ray(item, points)
            line_start_name = str(item.get("from") or str(item.get("ray") or "")[:1]).upper()
            line_start = _require_point(line_start_name, points)
            _draw_dashed_line(
                draw,
                line_start,
                point,
                fill=(214, 43, 43, 220),
                width=max(_AUXILIARY_LINE_WIDTH, _AUXILIARY_LINE_WIDTH * display_scale),
            )
            points[point_name] = point
            computed_points[point_name] = _point_payload(point, display_scale=display_scale)
            _draw_point(draw, point, label=point_name, font=font, scale=display_scale)
            supported_operation_count += 1
        elif op == "point_on_perpendicular_by_distance":
            point_name, point, vertex = _construct_point_on_perpendicular(item, points)
            _draw_dashed_line(
                draw,
                vertex,
                point,
                fill=(214, 43, 43, 220),
                width=max(_AUXILIARY_LINE_WIDTH, _AUXILIARY_LINE_WIDTH * display_scale),
            )
            points[point_name] = point
            computed_points[point_name] = _point_payload(point, display_scale=display_scale)
            _draw_point(draw, point, label=point_name, font=font, scale=display_scale)
            supported_operation_count += 1
        elif op == "connect_points":
            pair = item.get("points") or []
            if len(pair) != 2:
                raise _overlay_error(f"connect_points requires 2 points: {pair}")
            a = _require_point(str(pair[0]), points)
            b = _require_point(str(pair[1]), points)
            _draw_dashed_line(
                draw,
                a,
                b,
                fill=(214, 43, 43, 220),
                width=max(_AUXILIARY_LINE_WIDTH, _AUXILIARY_LINE_WIDTH * display_scale),
            )
            supported_operation_count += 1
        elif op == "highlight_segment":
            pair = item.get("points") or item.get("segment") or []
            if isinstance(pair, str):
                pair = list(pair)
            if len(pair) != 2:
                raise _overlay_error(f"highlight_segment requires 2 points: {pair}")
            a = _require_point(str(pair[0]), points)
            b = _require_point(str(pair[1]), points)
            _draw_dashed_line(
                draw,
                a,
                b,
                fill=(74, 115, 224, 190),
                width=max(_HIGHLIGHT_LINE_WIDTH, _HIGHLIGHT_LINE_WIDTH * display_scale),
            )
            supported_operation_count += 1
        elif op == "right_angle_marker":
            at = str(item.get("at") or item.get("point") or "")
            if at:
                _draw_right_angle_marker(draw, _require_point(at, points), scale=display_scale)
                supported_operation_count += 1
        elif op == "note":
            text = str(item.get("text") or "")
            anchor = item.get("at") or item.get("point")
            if text and anchor:
                point = _require_point(str(anchor), points)
                draw.text((point[0] + 8 * display_scale, point[1] + 8 * display_scale), text, fill=(120, 40, 40, 230), font=font)
                supported_operation_count += 1
        else:
            warnings.append(f"unsupported_operation:{op}")

    if constructions and supported_operation_count == 0:
        raise _overlay_error(f"unsupported overlay operations: {warnings}")

    png_content = _image_to_png(image.convert("RGB"))
    asset_id = str(uuid4())
    image_url = f"/assets/{asset_id}.png"
    if asset_repository is not None and storage is not None:
        stored = await storage.save(
            asset_id=asset_id,
            content=png_content,
            extension=".png",
            prefix="figures",
        )
        image_url = stored["url"]
        await asset_repository.create_asset(
            AssetCreate(
                asset_id=asset_id,
                asset_type="figure_overlay",
                storage_backend=stored["storage_backend"],
                object_key=stored["object_key"],
                url=stored["url"],
                filename=f"{asset_id}.png",
                mime_type="image/png",
                size_bytes=len(png_content),
                width=image.width,
                height=image.height,
                session_id=session_id,
                message_id=message_id,
                metadata={
                    "plan_type": overlay_plan.get("plan_type", "overlay_on_crop"),
                    "computed_points": computed_points,
                    "warnings": warnings,
                },
            )
        )

    return {
        "asset_id": asset_id,
        "image_url": image_url,
        "mime_type": "image/png",
        "width": image.width,
        "height": image.height,
        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
        "render_mode": "overlay_on_crop",
        "computed_points": computed_points,
        "warnings": warnings,
    }


def inspect_overlay_semantics(
    *,
    overlay_plan: dict[str, Any],
    localized_points: dict[str, Any],
    render_result: dict[str, Any],
    figure_goal: dict[str, Any] | None = None,
    auxiliary_text: str = "",
) -> dict[str, Any] | None:
    """程序级检查 overlay 语义，发现问题时产出可交给 LLM 修正的 Observation。"""
    points = _normalize_points(localized_points, display_scale=1)
    for name, value in (render_result.get("computed_points") or {}).items():
        point = _point_from_payload(value)
        if point is not None:
            points[str(name).upper()] = point

    expected_connections = _expected_connections(auxiliary_text, figure_goal or {})
    planned_connections = _planned_connections(overlay_plan)
    missing: list[str] = []
    wrong: list[str] = []
    warnings = list(render_result.get("warnings") or [])

    for pair in sorted(expected_connections):
        if pair not in planned_connections:
            missing.append(f"缺少辅助线 {''.join(pair)}")

    for left, right in _expected_equal_lengths(auxiliary_text, figure_goal or {}):
        left_len = _segment_length(left, points)
        right_len = _segment_length(right, points)
        if left_len is None or right_len is None:
            missing.append(f"无法检查 {left}={right}，缺少相关点位")
            continue
        tolerance = max(6.0, right_len * 0.12)
        if abs(left_len - right_len) > tolerance:
            wrong.append(f"{left} 应等于 {right}，当前 {left}={left_len:.1f}，{right}={right_len:.1f}")

    for left, right in _expected_perpendiculars(auxiliary_text, figure_goal or {}):
        issue = _perpendicular_issue(left, right, points)
        if issue:
            wrong.append(issue)

    for ray, after, point in _expected_ray_extensions(auxiliary_text, figure_goal or {}):
        issue = _ray_extension_issue(ray, after, point, points)
        if issue:
            wrong.append(issue)

    if not missing and not wrong and not warnings:
        return None

    suggested_fix = "；".join(missing + wrong + warnings)
    return {
        "tool": "overlay_programmatic_checker",
        "execution": {"ok": True, "error": "", "timeout": False},
        "image_quality": {"ok": True, "non_blank": True},
        "security_blocked": False,
        "score": 55,
        "next_action": "revise_code",
        "semantic_programmatic": {
            "missing": missing,
            "wrong": wrong,
            "warnings": warnings,
            "expected_connections": ["".join(pair) for pair in sorted(expected_connections)],
            "planned_connections": ["".join(pair) for pair in sorted(planned_connections)],
        },
        "suggested_fix": suggested_fix,
    }


def _expected_connections(auxiliary_text: str, figure_goal: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    pairs.update(_connection_pairs_from_text(auxiliary_text))

    for text in _goal_texts(figure_goal):
        if "connect" in text.lower() or "connected" in text.lower():
            for pair in re.findall(r"\b[A-Z]{2}\b", text.upper()):
                pairs.add(_pair_key(pair))
        pairs.update(_connection_pairs_from_text(text))
    return pairs


def _planned_connections(overlay_plan: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in overlay_plan.get("constructions") or []:
        if not isinstance(item, dict):
            continue
        op = item.get("op")
        if op in {"connect_points", "highlight_segment"}:
            pair = item.get("points") or item.get("segment") or []
            if isinstance(pair, str):
                pair = list(pair)
            if isinstance(pair, list) and len(pair) == 2:
                pairs.add(_pair_key(f"{pair[0]}{pair[1]}"))
        elif op == "point_on_perpendicular_by_distance":
            point = str(item.get("point") or "").upper()
            vertex = str(item.get("vertex") or item.get("from") or "").upper()
            if point and vertex:
                pairs.add(_pair_key(f"{vertex}{point}"))
    return pairs


def _expected_equal_lengths(auxiliary_text: str, figure_goal: dict[str, Any]) -> list[tuple[str, str]]:
    texts = [auxiliary_text, *_goal_texts(figure_goal)]
    pairs: list[tuple[str, str]] = []
    for text in texts:
        normalized = _normalize_geometry_text(text)
        for left, right in re.findall(r"(?<![A-Z])([A-Z]{2})\s*=\s*([A-Z]{2})(?![A-Z])", normalized):
            pairs.append((left, right))
    return pairs


def _expected_perpendiculars(auxiliary_text: str, figure_goal: dict[str, Any]) -> list[tuple[str, str]]:
    texts = [auxiliary_text, *_goal_texts(figure_goal)]
    pairs: list[tuple[str, str]] = []
    for text in texts:
        normalized = _normalize_geometry_text(text)
        for left, right in re.findall(r"(?<![A-Z])([A-Z]{2})\s*⊥\s*([A-Z]{2})(?![A-Z])", normalized):
            pairs.append((left, right))
    return pairs


def _expected_ray_extensions(auxiliary_text: str, figure_goal: dict[str, Any]) -> list[tuple[str, str, str]]:
    extensions: list[tuple[str, str, str]] = []
    for first, second, point in re.findall(
        r"延长\s*([A-Za-z])\s*([A-Za-z])\s*(?:至|到)\s*点?\s*([A-Za-z])",
        auxiliary_text,
    ):
        ray = f"{first}{second}".upper()
        extensions.append((ray, second.upper(), point.upper()))

    for item in (figure_goal.get("layout_hint") or {}).get("directed_rays") or []:
        if not isinstance(item, dict):
            continue
        ray = str(item.get("ray") or "").upper()
        if len(ray) == 2:
            for text in _goal_texts(figure_goal):
                for point in re.findall(r"\b([A-Z])\b(?=.*\bray\b)", text.upper()):
                    if point not in set(ray):
                        extensions.append((ray, ray[1], point))
                        break
    return extensions


def _goal_texts(figure_goal: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("normalized_auxiliary_intent", "auxiliary_intent"):
        if figure_goal.get(key):
            values.append(str(figure_goal[key]))
    expected = figure_goal.get("expected_auxiliary")
    if isinstance(expected, list):
        values.extend(str(item) for item in expected)
    elif expected:
        values.append(str(expected))
    return values


def build_overlay_plan_from_auxiliary_text(auxiliary_text: str) -> dict[str, Any] | None:
    """将无歧义辅助线文本转换为 overlay plan；无法识别时返回 None 交给 LLM。"""
    text = _normalize_geometry_text(auxiliary_text)
    perpendicular_match = re.search(
        r"过点\s*([A-Z])\s*作\s*([A-Z]{2})\s*⊥\s*([A-Z]{2}).*?"
        r"(?:使)?\s*\2\s*=\s*([A-Z]{2})",
        text,
    )
    if perpendicular_match is None:
        return None

    vertex = perpendicular_match.group(1)
    constructed_segment = perpendicular_match.group(2)
    perpendicular_to = perpendicular_match.group(3)
    distance = perpendicular_match.group(4)
    if vertex not in constructed_segment:
        return None
    point = constructed_segment.replace(vertex, "", 1)
    if len(point) != 1:
        return None

    side_reference = ""
    side_match = re.search(
        rf"点\s*{point}\s*与点\s*([A-Z])\s*位于直线\s*{perpendicular_to}\s*同侧",
        text,
    )
    if side_match:
        side_reference = side_match.group(1)

    constructions: list[dict[str, Any]] = [{
        "op": "point_on_perpendicular_by_distance",
        "point": point,
        "vertex": vertex,
        "perpendicular_to": perpendicular_to,
        "distance": distance,
    }]
    if side_reference:
        constructions[0]["side_reference"] = side_reference
    for pair in sorted(_connection_pairs_from_text(text)):
        constructions.append({"op": "connect_points", "points": [pair[0], pair[1]]})

    return {
        "plan_type": "overlay_on_crop",
        "coordinate_space": "crop_pixels",
        "intent": auxiliary_text,
        "constructions": constructions,
        "warnings": [],
        "_local": {"source": "auxiliary_text"},
    }


def _normalize_geometry_text(text: str) -> str:
    return (
        str(text or "")
        .upper()
        .replace("$", "")
        .replace("\\PERP", "⊥")
        .replace(" ", "")
    )


def _connection_pairs_from_text(text: str) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    normalized = _normalize_geometry_text(text)
    for match in re.finditer(r"连接(?:线段)?([A-Z]{2}(?:[、,，和及][A-Z]{2})*)", normalized):
        for pair in re.findall(r"[A-Z]{2}", match.group(1)):
            pairs.add(_pair_key(pair))
    return pairs


def _segment_length(segment: str, points: dict[str, Point]) -> float | None:
    if len(segment) != 2:
        return None
    a = points.get(segment[0])
    b = points.get(segment[1])
    if a is None or b is None:
        return None
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _perpendicular_issue(left: str, right: str, points: dict[str, Point]) -> str:
    if len(left) != 2 or len(right) != 2:
        return ""
    left_a = points.get(left[0])
    left_b = points.get(left[1])
    right_a = points.get(right[0])
    right_b = points.get(right[1])
    if left_a is None or left_b is None or right_a is None or right_b is None:
        return f"无法检查 {left} 是否垂直 {right}，缺少相关点位"
    left_vector = (left_b[0] - left_a[0], left_b[1] - left_a[1])
    right_vector = (right_b[0] - right_a[0], right_b[1] - right_a[1])
    left_len = math.hypot(left_vector[0], left_vector[1])
    right_len = math.hypot(right_vector[0], right_vector[1])
    if left_len <= 1e-6 or right_len <= 1e-6:
        return f"无法检查 {left} 是否垂直 {right}，线段长度为 0"
    cosine = abs(left_vector[0] * right_vector[0] + left_vector[1] * right_vector[1]) / (left_len * right_len)
    if cosine > 0.18:
        return f"{left} 应垂直 {right}，当前夹角偏差过大"
    return ""


def _ray_extension_issue(ray: str, after: str, point: str, points: dict[str, Point]) -> str:
    if len(ray) != 2:
        return ""
    start = points.get(ray[0])
    through = points.get(ray[1])
    target = points.get(point)
    if start is None or through is None or target is None:
        return f"无法检查 {point} 是否在 {ray} 延长线上，缺少相关点位"

    ray_vector = (through[0] - start[0], through[1] - start[1])
    target_vector = (target[0] - through[0], target[1] - through[1])
    ray_length = math.hypot(ray_vector[0], ray_vector[1])
    if ray_length <= 1e-6:
        return f"无法检查 {ray} 延长线，{ray} 长度为 0"

    cross = abs(ray_vector[0] * target_vector[1] - ray_vector[1] * target_vector[0]) / ray_length
    dot = ray_vector[0] * target_vector[0] + ray_vector[1] * target_vector[1]
    if cross > max(6.0, ray_length * 0.08):
        return f"{point} 不在 {ray} 所在直线上"
    if after == ray[1] and dot <= max(4.0, ray_length * 0.05):
        return f"{point} 不在 {after} 外侧"
    return ""


def _pair_key(pair: str) -> tuple[str, str]:
    normalized = str(pair).upper().replace(" ", "")
    if len(normalized) < 2:
        return ("", "")
    a, b = normalized[0], normalized[1]
    return tuple(sorted((a, b)))


def infer_layout_crop_box(
    image_path: str | Path,
    *,
    target_label: str,
) -> list[int] | None:
    """从页面布局中推断图1/图2/备用图对应的几何图裁剪框。"""
    target_index = _target_diagram_index(target_label)
    if target_index is None:
        return None

    image = Image.open(Path(image_path)).convert("L")
    width, height = image.size
    y0 = int(height * 0.38)
    y1 = int(height * 0.66)
    if y1 <= y0:
        return None

    pixels = image.load()
    bin_width = max(20, width // 60)
    active_threshold = max(20, int((y1 - y0) * bin_width * 0.0024))
    segments: list[tuple[int, int]] = []
    in_segment = False
    segment_start = 0
    bins: list[tuple[int, int, int]] = []
    for left in range(0, width, bin_width):
        right = min(width, left + bin_width)
        score = 0
        for x in range(left, right):
            for y in range(y0, y1):
                if pixels[x, y] < 70:
                    score += 1
        bins.append((left, right, score))

    for index, (left, right, score) in enumerate(bins):
        active = score > active_threshold
        if active and not in_segment:
            segment_start = left
            in_segment = True
        if in_segment and (not active or index == len(bins) - 1):
            segment_end = right if active and index == len(bins) - 1 else left
            if segment_end - segment_start > max(80, int(width * 0.035)):
                segments.append((segment_start, segment_end))
            in_segment = False

    if len(segments) <= target_index:
        return None

    left, right = segments[target_index]
    x_scan_margin = max(8, int(bin_width * 0.8))
    scan_left = max(0, left - x_scan_margin)
    scan_right = min(width, right + x_scan_margin)
    row_threshold = max(8, width // 150)
    y_min = int(height * 0.35)
    y_max = int(height * 0.725)
    rows: list[int] = []
    for y in range(max(0, y_min), min(height, y_max)):
        score = 0
        for x in range(scan_left, scan_right):
            if pixels[x, y] < 70:
                score += 1
        if score > row_threshold:
            rows.append(y)
    if not rows:
        return None

    top = min(rows)
    bottom = max(rows)
    x_margin = max(24, int((right - left) * 0.14))
    top_margin = max(30, int((bottom - top) * 0.135))
    bottom_margin = max(30, int((bottom - top) * 0.12))
    return [
        max(0, left - x_margin),
        max(0, top - top_margin),
        min(width, right + x_margin),
        min(height, bottom + bottom_margin),
    ]


def snap_localized_points_to_geometry(
    image_path: str | Path,
    localized_points: dict[str, Any],
    *,
    search_radius: int = 42,
) -> dict[str, Any]:
    """把 VLM 粗坐标吸附到局部几何线条端点/交点。

    该函数只修正坐标，不改变点名或辅助线语义；找不到可靠候选时保留原坐标。
    """
    image = Image.open(Path(image_path)).convert("L")
    gray = np.asarray(image, dtype=np.uint8)
    dark_mask = _dark_geometry_mask(gray)
    support_mask = _dilate_mask(dark_mask)
    component_labels, component_stats = _connected_component_stats(dark_mask)

    snapped_points: dict[str, dict[str, Any]] = {}
    raw_points: dict[str, dict[str, Any]] = {}
    adjustments: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for raw_label, value in localized_points.items():
        label = str(raw_label).upper()
        point = _point_from_payload(value)
        if point is None:
            warnings.append(f"point_snap_invalid:{raw_label}")
            continue

        x, y = point
        raw_payload = _copy_point_payload(value, x=x, y=y)
        raw_points[label] = raw_payload

        candidate = _best_snap_candidate(
            dark_mask=dark_mask,
            support_mask=support_mask,
            component_labels=component_labels,
            component_stats=component_stats,
            x=x,
            y=y,
            radius=max(8, int(search_radius)),
        )
        if candidate is None:
            snapped_points[label] = raw_payload
            adjustments[label] = {
                "snapped": False,
                "x": raw_payload["x"],
                "y": raw_payload["y"],
                "delta": 0.0,
                "snap_confidence": 0.0,
            }
            warnings.append(f"point_snap_no_candidate:{label}")
            continue

        snap_x, snap_y, score = candidate
        delta = math.hypot(snap_x - x, snap_y - y)
        snapped_payload = _copy_point_payload(value, x=snap_x, y=snap_y)
        snapped_payload["snap_confidence"] = round(min(1.0, score / 420.0), 3)
        snapped_payload["snap_delta"] = round(delta, 3)
        snapped_points[label] = snapped_payload
        adjustments[label] = {
            "snapped": delta > 1.0,
            "x": snapped_payload["x"],
            "y": snapped_payload["y"],
            "delta": round(delta, 3),
            "snap_confidence": snapped_payload["snap_confidence"],
            "score": round(score, 3),
        }

    return {
        "points": snapped_points,
        "raw_points": raw_points,
        "adjustments": adjustments,
        "warnings": warnings,
    }


def _normalize_crop_box(
    crop_box: list[int | float] | tuple[int | float, int | float, int | float, int | float] | None,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    if not crop_box or len(crop_box) != 4:
        return (0, 0, width, height)
    left, top, right, bottom = [int(round(float(value))) for value in crop_box]
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return (left, top, right, bottom)


def _target_diagram_index(target_label: str) -> int | None:
    label = str(target_label or "")
    if "图1" in label or "图 1" in label:
        return 0
    if "图2" in label or "图 2" in label:
        return 1
    if "备用" in label:
        return 2
    return None


def _dark_column_scores(
    image: Image.Image,
    *,
    y0: int,
    y1: int,
    threshold: int,
) -> list[int]:
    pixels = image.load()
    width, _ = image.size
    scores: list[int] = []
    for x in range(width):
        score = 0
        for y in range(y0, y1):
            if pixels[x, y] < threshold:
                score += 1
        scores.append(score)
    return scores


def _smooth_scores(scores: list[int], *, radius: int) -> list[float]:
    smoothed: list[float] = []
    for index in range(len(scores)):
        left = max(0, index - radius)
        right = min(len(scores), index + radius + 1)
        smoothed.append(sum(scores[left:right]) / max(1, right - left))
    return smoothed


def _score_clusters(
    scores: list[float],
    *,
    min_score: float,
    min_width: int,
) -> list[tuple[int, int]]:
    clusters: list[tuple[int, int]] = []
    start: int | None = None
    for index, score in enumerate(scores):
        if score > min_score and start is None:
            start = index
            continue
        if start is not None and (score <= min_score or index == len(scores) - 1):
            end = index
            if end - start >= min_width:
                clusters.append((start, end))
            start = None
    return clusters


def _dark_bbox(
    image: Image.Image,
    *,
    left: int,
    right: int,
    y0: int,
    y1: int,
) -> tuple[int, int, int, int] | None:
    pixels = image.load()
    xs: list[int] = []
    ys: list[int] = []
    for x in range(left, right):
        for y in range(y0, y1):
            if pixels[x, y] < 90:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _point_from_payload(value: Any) -> Point | None:
    if isinstance(value, dict):
        x = value.get("x")
        y = value.get("y")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x, y = value[0], value[1]
    else:
        return None
    if x is None or y is None:
        return None
    try:
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def _copy_point_payload(value: Any, *, x: float, y: float) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    payload["x"] = int(round(x))
    payload["y"] = int(round(y))
    return payload


def _dark_geometry_mask(gray: np.ndarray) -> np.ndarray:
    threshold = min(180, max(65, int(np.percentile(gray, 25)) - 35))
    return gray <= threshold


def _dilate_mask(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    result = np.zeros_like(mask, dtype=bool)
    for dy in range(3):
        for dx in range(3):
            result |= padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return result


def _best_snap_candidate(
    *,
    dark_mask: np.ndarray,
    support_mask: np.ndarray,
    component_labels: np.ndarray,
    component_stats: list[dict[str, int]],
    x: float,
    y: float,
    radius: int,
) -> tuple[float, float, float] | None:
    height, width = dark_mask.shape
    left = max(0, int(math.floor(x - radius)))
    right = min(width, int(math.ceil(x + radius + 1)))
    top = max(0, int(math.floor(y - radius)))
    bottom = min(height, int(math.ceil(y + radius + 1)))
    if left >= right or top >= bottom:
        return None

    ys, xs = np.nonzero(dark_mask[top:bottom, left:right])
    if len(xs) == 0:
        return None

    candidate_pixels: list[tuple[int, int, float, dict[str, int]]] = []
    max_component_area = 0
    for local_x, local_y in zip(xs, ys, strict=False):
        candidate_x = float(left + int(local_x))
        candidate_y = float(top + int(local_y))
        distance = math.hypot(candidate_x - x, candidate_y - y)
        if distance > radius:
            continue
        component_id = int(component_labels[int(candidate_y), int(candidate_x)])
        stats = component_stats[component_id] if component_id < len(component_stats) else {"area": 0, "width": 0, "height": 0}
        max_component_area = max(max_component_area, stats["area"])
        candidate_pixels.append((int(candidate_x), int(candidate_y), distance, stats))

    best: tuple[float, float, float] | None = None
    for candidate_x, candidate_y, distance, stats in candidate_pixels:
        if _looks_like_isolated_label_component(stats, max_component_area):
            continue
        score = _geometry_candidate_score(
            support_mask,
            candidate_x,
            candidate_y,
            distance=distance,
        )
        if score < 90:
            continue
        if best is None or score > best[2]:
            best = (float(candidate_x), float(candidate_y), score)
    skeleton_candidate = _best_skeleton_junction_candidate(
        dark_mask=dark_mask,
        support_mask=support_mask,
        component_labels=component_labels,
        component_stats=component_stats,
        max_component_area=max_component_area,
        left=left,
        right=right,
        top=top,
        bottom=bottom,
        x=x,
        y=y,
        radius=radius,
    )
    if skeleton_candidate is not None:
        if best is None or skeleton_candidate[2] >= best[2] * 0.55:
            return skeleton_candidate
    return best


def _best_skeleton_junction_candidate(
    *,
    dark_mask: np.ndarray,
    support_mask: np.ndarray,
    component_labels: np.ndarray,
    component_stats: list[dict[str, int]],
    max_component_area: int,
    left: int,
    right: int,
    top: int,
    bottom: int,
    x: float,
    y: float,
    radius: int,
) -> tuple[float, float, float] | None:
    roi = dark_mask[top:bottom, left:right].copy()
    for local_y, local_x in zip(*np.nonzero(roi), strict=False):
        component_id = int(component_labels[top + int(local_y), left + int(local_x)])
        stats = component_stats[component_id] if component_id < len(component_stats) else {"area": 0, "width": 0, "height": 0}
        if _looks_like_isolated_label_component(stats, max_component_area):
            roi[int(local_y), int(local_x)] = False

    skeleton = _skeletonize_mask(roi)
    candidates: list[tuple[float, float, float, float]] = []
    for local_y, local_x in zip(*np.nonzero(skeleton), strict=False):
        if _skeleton_neighbor_count(skeleton, int(local_x), int(local_y)) < 3:
            continue
        candidate_x = float(left + int(local_x))
        candidate_y = float(top + int(local_y))
        distance = math.hypot(candidate_x - x, candidate_y - y)
        if distance > radius:
            continue
        score = _geometry_candidate_score(
            support_mask,
            int(candidate_x),
            int(candidate_y),
            distance=distance,
        )
        if score < 90:
            continue
        candidates.append((distance, candidate_x, candidate_y, score))

    if not candidates:
        return None
    _, candidate_x, candidate_y, score = min(candidates, key=lambda item: item[0])
    return candidate_x, candidate_y, score


def _skeletonize_mask(mask: np.ndarray) -> np.ndarray:
    image = np.pad(mask.astype(bool), 1, mode="constant", constant_values=False)
    changed = True
    iteration_count = 0
    while changed and iteration_count < 80:
        changed = False
        iteration_count += 1
        for phase in (0, 1):
            pixels_to_remove: list[tuple[int, int]] = []
            for y in range(1, image.shape[0] - 1):
                for x in range(1, image.shape[1] - 1):
                    if not image[y, x]:
                        continue
                    neighbors = [
                        image[y - 1, x],
                        image[y - 1, x + 1],
                        image[y, x + 1],
                        image[y + 1, x + 1],
                        image[y + 1, x],
                        image[y + 1, x - 1],
                        image[y, x - 1],
                        image[y - 1, x - 1],
                    ]
                    black_neighbor_count = sum(bool(value) for value in neighbors)
                    if black_neighbor_count < 2 or black_neighbor_count > 6:
                        continue
                    if _skeleton_transition_count(neighbors) != 1:
                        continue
                    p2, p4, p6, p8 = neighbors[0], neighbors[2], neighbors[4], neighbors[6]
                    if phase == 0:
                        if p2 and p4 and p6:
                            continue
                        if p4 and p6 and p8:
                            continue
                    else:
                        if p2 and p4 and p8:
                            continue
                        if p2 and p6 and p8:
                            continue
                    pixels_to_remove.append((y, x))
            if pixels_to_remove:
                changed = True
                for y, x in pixels_to_remove:
                    image[y, x] = False
    return image[1:-1, 1:-1]


def _skeleton_transition_count(neighbors: list[bool]) -> int:
    loop = neighbors + [neighbors[0]]
    return sum((not loop[index]) and loop[index + 1] for index in range(8))


def _skeleton_neighbor_count(skeleton: np.ndarray, x: int, y: int) -> int:
    count = 0
    for next_y in range(max(0, y - 1), min(skeleton.shape[0], y + 2)):
        for next_x in range(max(0, x - 1), min(skeleton.shape[1], x + 2)):
            if next_x == x and next_y == y:
                continue
            if skeleton[next_y, next_x]:
                count += 1
    return count


def _connected_component_stats(mask: np.ndarray) -> tuple[np.ndarray, list[dict[str, int]]]:
    height, width = mask.shape
    labels = np.zeros(mask.shape, dtype=np.int32)
    stats: list[dict[str, int]] = [{"area": 0, "width": 0, "height": 0}]
    component_id = 0

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or labels[y, x] != 0:
                continue
            component_id += 1
            stack = [(x, y)]
            labels[y, x] = component_id
            area = 0
            min_x = max_x = x
            min_y = max_y = y

            while stack:
                current_x, current_y = stack.pop()
                area += 1
                min_x = min(min_x, current_x)
                max_x = max(max_x, current_x)
                min_y = min(min_y, current_y)
                max_y = max(max_y, current_y)
                for next_y in range(current_y - 1, current_y + 2):
                    if next_y < 0 or next_y >= height:
                        continue
                    for next_x in range(current_x - 1, current_x + 2):
                        if next_x < 0 or next_x >= width:
                            continue
                        if labels[next_y, next_x] != 0 or not mask[next_y, next_x]:
                            continue
                        labels[next_y, next_x] = component_id
                        stack.append((next_x, next_y))

            stats.append({
                "area": area,
                "width": max_x - min_x + 1,
                "height": max_y - min_y + 1,
            })

    return labels, stats


def _looks_like_isolated_label_component(stats: dict[str, int], max_component_area: int) -> bool:
    if max_component_area < 900:
        return False
    max_dimension = max(stats["width"], stats["height"])
    return (
        stats["area"] < max_component_area * 0.65
        and stats["area"] < 1800
        and max_dimension <= 80
    )


def _geometry_candidate_score(
    support_mask: np.ndarray,
    x: int,
    y: int,
    *,
    distance: float,
) -> float:
    ray_supports = _ray_supports(support_mask, x, y)
    half = len(ray_supports) // 2
    axis_supports = [
        ray_supports[index] + ray_supports[index + half]
        for index in range(half)
    ]
    long_axes = [support for support in axis_supports if support >= 15]
    long_rays = [support for support in ray_supports if support >= 10]
    endpoint_axes = 0
    for index in range(half):
        a = ray_supports[index]
        b = ray_supports[index + half]
        if max(a, b) >= 13 and abs(a - b) >= 7:
            endpoint_axes += 1

    local_support = _local_support_count(support_mask, x, y, radius=2)
    return (
        len(long_axes) * 70.0
        + max(0, len(long_axes) - 1) * 115.0
        + len(long_rays) * 9.0
        + sum(sorted(axis_supports, reverse=True)[:3]) * 2.0
        + endpoint_axes * 22.0
        + local_support * 1.5
        - distance * 1.2
    )


def _ray_supports(mask: np.ndarray, x: int, y: int) -> list[int]:
    supports: list[int] = []
    for index in range(32):
        angle = (math.tau * index) / 32.0
        supports.append(
            _ray_support(mask, x, y, dx=math.cos(angle), dy=math.sin(angle))
        )
    return supports


def _ray_support(mask: np.ndarray, x: int, y: int, *, dx: float, dy: float) -> int:
    height, width = mask.shape
    support = 0
    misses = 0
    for step in range(1, 34):
        px = int(round(x + dx * step))
        py = int(round(y + dy * step))
        if px < 0 or py < 0 or px >= width or py >= height:
            break
        if mask[py, px]:
            support += 1
            misses = 0
        else:
            misses += 1
            if misses >= 3:
                break
    return support


def _local_support_count(mask: np.ndarray, x: int, y: int, *, radius: int) -> int:
    height, width = mask.shape
    left = max(0, x - radius)
    right = min(width, x + radius + 1)
    top = max(0, y - radius)
    bottom = min(height, y + radius + 1)
    return int(mask[top:bottom, left:right].sum())


def _normalize_points(localized_points: dict[str, Any], *, display_scale: int) -> dict[str, Point]:
    points: dict[str, Point] = {}
    for key, value in localized_points.items():
        name = str(key).upper()
        if isinstance(value, dict):
            x = value.get("x")
            y = value.get("y")
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            x, y = value[0], value[1]
        else:
            continue
        if x is None or y is None:
            continue
        points[name] = (float(x) * display_scale, float(y) * display_scale)
    return points


def _construct_point_on_ray(operation: dict[str, Any], points: dict[str, Point]) -> tuple[str, Point]:
    point_name = str(operation.get("point") or operation.get("new_point") or "").upper()
    if not point_name:
        raise _overlay_error("point_on_segment_by_distance missing point")
    ray = str(operation.get("ray") or "").upper()
    if len(ray) != 2:
        raise _overlay_error(f"invalid directed ray: {ray}")
    start_name = str(operation.get("from") or ray[0]).upper()
    ray_start = _require_point(ray[0], points)
    ray_through = _require_point(ray[1], points)
    start = _require_point(start_name, points)
    direction = (ray_through[0] - ray_start[0], ray_through[1] - ray_start[1])
    direction_len = math.hypot(direction[0], direction[1])
    if direction_len <= 1e-6:
        raise _overlay_error(f"ray {ray} has zero length")
    distance = _parse_distance(str(operation.get("distance") or ""), points)
    unit = (direction[0] / direction_len, direction[1] / direction_len)
    return point_name, (start[0] + unit[0] * distance, start[1] + unit[1] * distance)


def _construct_point_on_perpendicular(
    operation: dict[str, Any],
    points: dict[str, Point],
) -> tuple[str, Point, Point]:
    point_name = str(operation.get("point") or operation.get("new_point") or "").upper()
    if not point_name:
        raise _overlay_error("point_on_perpendicular_by_distance missing point")
    vertex_name = str(operation.get("vertex") or operation.get("from") or "").upper()
    if not vertex_name:
        raise _overlay_error("point_on_perpendicular_by_distance missing vertex")
    perpendicular_to = str(operation.get("perpendicular_to") or operation.get("line") or "").upper()
    if len(perpendicular_to) != 2:
        raise _overlay_error(f"invalid perpendicular reference: {perpendicular_to}")

    vertex = _require_point(vertex_name, points)
    line_a = _require_point(perpendicular_to[0], points)
    line_b = _require_point(perpendicular_to[1], points)
    line_vector = (line_b[0] - line_a[0], line_b[1] - line_a[1])
    line_len = math.hypot(line_vector[0], line_vector[1])
    if line_len <= 1e-6:
        raise _overlay_error(f"line {perpendicular_to} has zero length")
    distance = _parse_distance(str(operation.get("distance") or ""), points)
    unit_a = (-line_vector[1] / line_len, line_vector[0] / line_len)
    unit_b = (line_vector[1] / line_len, -line_vector[0] / line_len)
    candidates = [
        (vertex[0] + unit_a[0] * distance, vertex[1] + unit_a[1] * distance),
        (vertex[0] + unit_b[0] * distance, vertex[1] + unit_b[1] * distance),
    ]

    side_reference = str(operation.get("side_reference") or "").upper()
    if side_reference and side_reference in points:
        reference = points[side_reference]
        reference_side = _line_side(line_a, line_b, reference)
        if abs(reference_side) > 1e-6:
            same_side = [
                candidate
                for candidate in candidates
                if _line_side(line_a, line_b, candidate) * reference_side > 0
            ]
            if same_side:
                return point_name, same_side[0], vertex
    return point_name, candidates[0], vertex


def _line_side(start: Point, end: Point, point: Point) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])


def _parse_distance(expression: str, points: dict[str, Point]) -> float:
    expr = expression.strip().upper().replace(" ", "")
    if not expr:
        raise _overlay_error("distance expression missing")
    coefficient = 1.0
    segment = expr
    if "*" in expr:
        raw_coefficient, segment = expr.split("*", 1)
        try:
            coefficient = float(raw_coefficient)
        except ValueError as exc:
            raise _overlay_error(f"invalid distance coefficient: {expression}") from exc
    if len(segment) == 2 and segment.isalpha():
        a = _require_point(segment[0], points)
        b = _require_point(segment[1], points)
        return coefficient * math.hypot(b[0] - a[0], b[1] - a[1])
    try:
        return coefficient * float(segment)
    except ValueError as exc:
        raise _overlay_error(f"unsupported distance expression: {expression}") from exc


def _require_point(name: str, points: dict[str, Point]) -> Point:
    key = name.upper()
    if key not in points:
        raise _overlay_error(f"missing point: {key}")
    return points[key]


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    *,
    fill: tuple[int, int, int, int],
    width: int,
    dash: int = 12,
    gap: int = 8,
) -> None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return
    ux = dx / length
    uy = dy / length
    distance = 0.0
    while distance < length:
        segment_end = min(distance + dash, length)
        a = (start[0] + ux * distance, start[1] + uy * distance)
        b = (start[0] + ux * segment_end, start[1] + uy * segment_end)
        draw.line([a, b], fill=fill, width=width)
        distance += dash + gap


def _draw_point(
    draw: ImageDraw.ImageDraw,
    point: Point,
    *,
    label: str,
    font: ImageFont.ImageFont,
    scale: int,
) -> None:
    radius = max(5, 5 * scale)
    draw.ellipse(
        [point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius],
        fill=(214, 43, 43, 230),
    )
    draw.text(
        (point[0] + 6 * scale, point[1] - 22 * scale),
        label,
        fill=(160, 30, 30, 240),
        font=font,
        stroke_width=max(2, int(round(1.5 * scale))),
        stroke_fill=(255, 245, 245, 230),
    )


def _draw_right_angle_marker(draw: ImageDraw.ImageDraw, point: Point, *, scale: int) -> None:
    size = 12 * scale
    x, y = point
    draw.line(
        [(x, y), (x + size, y), (x + size, y - size), (x, y - size)],
        fill=(74, 115, 224, 220),
        width=max(2, 2 * scale),
    )


def _point_payload(point: Point, *, display_scale: int) -> dict[str, float]:
    return {"x": point[0] / display_scale, "y": point[1] / display_scale}


def _load_font(*, size: int) -> ImageFont.ImageFont:
    for font_name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _image_to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _overlay_error(message: str) -> OverlayRenderError:
    return OverlayRenderError(
        message,
        observation={
            "execution": {"ok": False, "error": message},
            "image_quality": {"ok": False, "non_blank": False},
            "security_blocked": False,
            "score": 0,
            "next_action": "revise_code",
        },
    )
