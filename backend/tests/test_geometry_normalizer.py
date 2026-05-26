# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""结构化几何场景归一化测试。"""

from app.agent.geometry_normalizer import normalize_geometry_scene


def test_normalize_geometry_scene_extracts_text_relations_and_visual_facts():
    question_text = (
        "如图，∠BCA = 90°，CA = CB，D 在线段 BA 上，"
        "∠CEA = 90°，延长 EA 与 CD 交于 H，连接 BH，"
        "且 AH + 2AE = BH，求证 AH ⊥ BH。"
    )
    visual_observation = {
        "points": [{"id": point, "confidence": 0.9} for point in "ABCDEH"],
        "drawn_segments": [
            {"endpoints": ["C", "A"], "confidence": 0.9},
            {"endpoints": ["C", "B"], "confidence": 0.9},
            {"endpoints": ["B", "H"], "confidence": 0.8},
        ],
        "marks": [],
        "uncertain": [],
    }

    scene = normalize_geometry_scene(
        question_text=question_text,
        diagram_description="图中有 A、B、C、D、E、H 点和 BH 连线",
        has_figure=True,
        visual_observation=visual_observation,
    )

    assert scene is not None
    assert scene["version"] == "1.0"
    assert {point["id"] for point in scene["observations"]["points"]} >= set("ABCDEH")
    assert {"points": ["B", "H"]} in [
        rel["refs"] for rel in scene["given_relations"] if rel["type"] == "connected"
    ]
    relation_types = {rel["type"] for rel in scene["given_relations"]}
    assert "perpendicular" in relation_types
    assert "equal_length" in relation_types
    assert "point_on_line" in relation_types
    assert "collinear" in relation_types
    assert {
        "expression": "AH + 2AE = BH"
    } in [rel["refs"] for rel in scene["given_relations"] if rel["type"] == "length_expression"]


def test_normalize_geometry_scene_returns_none_for_non_geometry_question():
    scene = normalize_geometry_scene(
        question_text="求函数 f(x)=x^2 的最小值。",
        diagram_description="",
        has_figure=False,
        visual_observation=None,
    )

    assert scene is None


def test_normalize_geometry_scene_records_visual_parse_warning():
    scene = normalize_geometry_scene(
        question_text="如图，连接 AB。",
        diagram_description="线段 AB",
        has_figure=True,
        visual_observation="not-a-dict",
    )

    assert scene is not None
    assert scene["warnings"]
    assert scene["warnings"][0]["code"] == "invalid_visual_observation"
