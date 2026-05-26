# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""从 `【辅助线】` 句中抽取受控辅助操作。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any


def extract_auxiliary_operations(
    solve_content: str,
    *,
    fallback_parser: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """抽取辅助线操作。

    只读取以 `【辅助线】` 开头的句子，正文中的几何动词不会触发抽取。
    """
    sentence = _find_auxiliary_sentence(solve_content)
    if not sentence:
        return {"operations": [], "warnings": []}
    sentence = _normalize_auxiliary_sentence(sentence)

    operations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    next_id = 1

    for match in re.finditer(r"延长\s*([A-Z]{2})\s*至点?\s*([A-Z])\s*，?\s*使\s*([A-Z]{2})\s*=\s*([A-Z]{2})", sentence):
        line, new_point, target_segment, distance_ref = match.groups()
        operations.append(_operation(
            next_id,
            "construct_point_on_ray_with_distance",
            {
                "ray": line,
                "base_point": target_segment[0],
                "distance_ref": distance_ref,
                "new_point": new_point,
            },
            sentence,
        ))
        next_id += 1

    for match in re.finditer(r"(?<!使\s)延长\s*([A-Z]{2})\s*至点?\s*([A-Z])", sentence):
        line, new_point = match.groups()
        if any(op["params"].get("new_point") == new_point for op in operations):
            continue
        operations.append(_operation(
            next_id,
            "extend_line",
            {"line": line, "through": line[1], "new_point": new_point},
            sentence,
        ))
        next_id += 1

    for segment, point in re.findall(r"取\s*([A-Z]{2})\s*的中点\s*([A-Z])", sentence):
        operations.append(_operation(
            next_id,
            "midpoint",
            {"segment": segment, "new_point": point},
            sentence,
        ))
        next_id += 1

    for a, b, point in re.findall(r"([A-Z]{2})\s*与\s*([A-Z]{2})\s*交于\s*([A-Z])", sentence):
        operations.append(_operation(
            next_id,
            "intersection",
            {"a": a, "b": b, "new_point": point},
            sentence,
        ))
        next_id += 1

    for point, segment, line, intersect_line, foot in re.findall(
        r"过点?\s*([A-Z])\s*作\s*([A-Z]{2})\s*[⊥垂直]\s*(?:直线)?\s*([A-Z]{2})"
        r"\s*交(?:直线)?\s*([A-Z]{2})\s*(?:的延长线)?\s*于点?\s*([A-Z])",
        sentence,
    ):
        if intersect_line == line:
            continue
        operations.append(_operation(
            next_id,
            "construct_perpendicular_intersection",
            {
                "point": point,
                "line": line,
                "intersect_line": intersect_line,
                "foot": foot,
                "segment": segment,
            },
            sentence,
        ))
        next_id += 1

    for point, segment, line, _intersect_line, foot in re.findall(
        r"过点?\s*([A-Z])\s*作\s*([A-Z]{2})\s*[⊥垂直]\s*(?:直线)?\s*([A-Z]{2})"
        r"(?:\s*交(?:直线)?\s*([A-Z]{2})\s*(?:的延长线)?\s*于点?\s*([A-Z]))?",
        sentence,
    ):
        if any(op["params"].get("foot") == (foot or segment[1]) for op in operations):
            continue
        operations.append(_operation(
            next_id,
            "construct_perpendicular",
            {"point": point, "line": line, "foot": foot or segment[1], "segment": segment},
            sentence,
        ))
        next_id += 1

    for point, segment, line in re.findall(
        r"过点?\s*([A-Z])\s*作\s*([A-Z]{2})\s*[∥平行]\s*(?:直线)?\s*([A-Z]{2})",
        sentence,
    ):
        operations.append(_operation(
            next_id,
            "construct_parallel",
            {"point": point, "line": line, "new_line": segment},
            sentence,
        ))
        next_id += 1

    for match in re.finditer(
        r"在\s*([A-Z]{2})\s*上截取一点?\s*([A-Z])\s*，?\s*使\s*([A-Z]{2})\s*=\s*([A-Z]{2})",
        sentence,
    ):
        line, new_point, copied_segment, distance_ref = match.groups()
        base_point = copied_segment[0]
        if base_point not in line:
            continue
        other_point = line[0] if line[1] == base_point else line[1]
        operations.append(_operation(
            next_id,
            "construct_point_on_ray_with_distance",
            {
                "ray": f"{base_point}{other_point}",
                "base_point": base_point,
                "distance_ref": distance_ref,
                "new_point": new_point,
            },
            sentence,
        ))
        next_id += 1

    for match in re.finditer(
        r"在\s*([A-Z]{2})\s*上截取\s*([A-Z]{2})\s*=\s*([A-Z]{2})",
        sentence,
    ):
        line, copied_segment, distance_ref = match.groups()
        base_point = copied_segment[0]
        new_point = copied_segment[1]
        if base_point not in line:
            continue
        other_point = line[0] if line[1] == base_point else line[1]
        operations.append(_operation(
            next_id,
            "construct_point_on_ray_with_distance",
            {
                "ray": f"{base_point}{other_point}",
                "base_point": base_point,
                "distance_ref": distance_ref,
                "new_point": new_point,
            },
            sentence,
        ))
        next_id += 1

    for match in re.finditer(r"(?:连接|连结)\s*([A-Z]{2}(?:[、,，]\s*[A-Z]{2})*)", sentence):
        for segment in re.findall(r"[A-Z]{2}", match.group(1)):
            operations.append(_operation(
                next_id,
                "connect",
                {"points": [segment[0], segment[1]]},
                sentence,
            ))
            next_id += 1

    if not operations and fallback_parser is not None:
        for fallback_op in fallback_parser(sentence):
            operation = dict(fallback_op)
            operation.setdefault("id", f"aux_{next_id}")
            operation.setdefault("source_sentence", sentence)
            operation.setdefault("confidence", 0.5)
            operations.append(operation)
            next_id += 1
        if operations:
            warnings.append({
                "code": "fallback_parser_used",
                "message": "规则解析失败，已使用文本模型兜底结果",
            })

    return {"operations": operations, "warnings": warnings}


def _normalize_auxiliary_sentence(sentence: str) -> str:
    normalized = sentence.replace("$", "")
    normalized = normalized.replace("\\perp", "⊥")
    normalized = normalized.replace("\\parallel", "∥")
    normalized = normalized.replace("\\,", "")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*([⊥∥、,，。])\s*", r"\1", normalized)
    return normalized.strip()


def _find_auxiliary_sentence(content: str) -> str | None:
    match = re.search(r"【辅助线】\s*([^\n]+)", content)
    if not match:
        for sentence in re.split(r"[。\n]", content):
            candidate = sentence.strip()
            if _looks_like_auxiliary_sentence(candidate):
                return candidate
        return None
    return match.group(1).strip()


def _looks_like_auxiliary_sentence(sentence: str) -> bool:
    return bool(re.search(
        r"(延长\s*[A-Z]{2}\s*至点?\s*[A-Z]"
        r"|在\s*[A-Z]{2}\s*上截取一点?\s*[A-Z]"
        r"|过点?\s*[A-Z]\s*作\s*[A-Z]{2}"
        r"|取\s*[A-Z]{2}\s*的中点"
        r"|[A-Z]{2}\s*与\s*[A-Z]{2}\s*交于"
        r"|作\s*[A-Z]{2}\s*[⊥垂直∥平行])",
        sentence,
    ))


def _operation(index: int, op_type: str, params: dict[str, Any], sentence: str) -> dict[str, Any]:
    return {
        "id": f"aux_{index}",
        "type": op_type,
        "params": params,
        "source_sentence": sentence,
        "confidence": 1.0,
    }
