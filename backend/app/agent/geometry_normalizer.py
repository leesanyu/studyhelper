# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""将题干和视觉事实归一化为结构化几何场景。"""

from __future__ import annotations

import re
from typing import Any

from app.agent.geometry_types import GeometryScene


_POINT_RE = re.compile(r"[A-Z][0-9]?")


def normalize_geometry_scene(
    *,
    question_text: str,
    diagram_description: str,
    has_figure: bool,
    visual_observation: dict[str, Any] | None,
) -> GeometryScene | None:
    """生成初版 `GeometrySceneCandidate`。

    归一化只记录题干或图中直接给出的事实，不做证明推导。
    """
    if not has_figure and not diagram_description and not _looks_like_geometry(question_text):
        return None

    warnings: list[dict[str, Any]] = []
    if visual_observation is None:
        visual = {}
    elif isinstance(visual_observation, dict):
        visual = visual_observation
    else:
        visual = {}
        warnings.append({
            "code": "invalid_visual_observation",
            "message": "visual_observation must be an object",
        })

    points = _normalize_points(visual.get("points", []), question_text)
    drawn_segments = _normalize_segments(visual.get("drawn_segments", []))
    marks = _normalize_marks(visual.get("marks", []))
    uncertain = list(visual.get("uncertain", [])) if isinstance(visual.get("uncertain", []), list) else []

    scene: GeometryScene = {
        "version": "1.0",
        "source": {
            "question_text": question_text,
            "diagram_description": diagram_description,
        },
        "observations": {
            "points": points,
            "drawn_segments": drawn_segments,
            "marks": marks,
        },
        "given_relations": _extract_relations(question_text),
        "auxiliaries": [],
        "uncertain": uncertain,
        "warnings": warnings,
    }
    return scene


def _looks_like_geometry(text: str) -> bool:
    return any(token in text for token in ("∠", "△", "线段", "垂直", "⊥", "平行", "连接", "交于"))


def _normalize_points(raw_points: Any, question_text: str) -> list[dict[str, Any]]:
    points: dict[str, dict[str, Any]] = {}
    if isinstance(raw_points, list):
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            point_id = str(item.get("id", "")).upper()
            if not _POINT_RE.fullmatch(point_id):
                continue
            normalized = {
                "id": point_id,
                "label": item.get("label", point_id),
                "source": item.get("source", "vision"),
                "confidence": float(item.get("confidence", 0.5)),
            }
            if "coordinate" in item:
                normalized["coordinate"] = item["coordinate"]
            if "evidence" in item:
                normalized["evidence"] = item["evidence"]
            points[point_id] = normalized

    for point_id in sorted(set(_POINT_RE.findall(question_text))):
        points.setdefault(point_id, {
            "id": point_id,
            "label": point_id,
            "source": "text",
            "confidence": 1.0,
        })
    return list(points.values())


def _normalize_segments(raw_segments: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    if not isinstance(raw_segments, list):
        return segments
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        endpoints = item.get("endpoints")
        if not _valid_point_pair(endpoints):
            continue
        a, b = [str(p).upper() for p in endpoints]
        segment = {
            "id": item.get("id", f"seg_{a}{b}"),
            "endpoints": [a, b],
            "source": item.get("source", "vision"),
            "confidence": float(item.get("confidence", 0.5)),
        }
        if "evidence" in item:
            segment["evidence"] = item["evidence"]
        segments.append(segment)
    return segments


def _normalize_marks(raw_marks: Any) -> list[dict[str, Any]]:
    return list(raw_marks) if isinstance(raw_marks, list) else []


def _extract_relations(question_text: str) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []

    for angle in re.findall(r"∠\s*([A-Z]{3})\s*=\s*90\s*°?", question_text):
        vertex = angle[1]
        relations.append({
            "type": "perpendicular",
            "refs": {"a": angle[1] + angle[0], "b": angle[1] + angle[2]},
            "source": "text",
            "confidence": 1.0,
            "evidence": f"∠{angle} = 90°",
        })

    for a, b in re.findall(r"(?<![+0-9A-Z])([A-Z]{2})\s*=\s*([A-Z]{2})(?![+0-9A-Z])", question_text):
        relations.append({
            "type": "equal_length",
            "refs": {"a": a, "b": b},
            "source": "text",
            "confidence": 1.0,
            "evidence": f"{a} = {b}",
        })

    for point, line in re.findall(r"([A-Z])\s*在线段\s*([A-Z]{2})\s*上", question_text):
        relations.append({
            "type": "point_on_line",
            "refs": {"point": point, "line": line, "between": [line[0], line[1]]},
            "source": "text",
            "confidence": 1.0,
            "evidence": f"{point} 在线段 {line} 上",
        })

    for line_a, line_b, point in re.findall(r"([A-Z]{2})\s*与\s*([A-Z]{2})\s*交于\s*([A-Z])", question_text):
        relations.append({
            "type": "collinear",
            "refs": {"points": [line_a[0], line_a[1], point], "ordered": False},
            "source": "text",
            "confidence": 1.0,
            "evidence": f"{line_a} 与 {line_b} 交于 {point}",
        })
        relations.append({
            "type": "collinear",
            "refs": {"points": [line_b[0], line_b[1], point], "ordered": False},
            "source": "text",
            "confidence": 1.0,
            "evidence": f"{line_a} 与 {line_b} 交于 {point}",
        })

    for segment in re.findall(r"连接\s*([A-Z]{2})", question_text):
        relations.append({
            "type": "connected",
            "refs": {"points": [segment[0], segment[1]]},
            "source": "text",
            "confidence": 1.0,
            "evidence": f"连接 {segment}",
        })

    for expression in re.findall(r"([A-Z]{2}\s*\+\s*\d*[A-Z]{2}\s*=\s*[A-Z]{2})", question_text):
        relations.append({
            "type": "length_expression",
            "refs": {"expression": re.sub(r"\s+", "", expression).replace("+", " + ").replace("=", " = ")},
            "source": "text",
            "confidence": 1.0,
            "evidence": expression,
        })

    return relations


def _valid_point_pair(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(point, str) and _POINT_RE.fullmatch(point.upper()) for point in value)
    )

