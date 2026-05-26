# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""辅助线句结构化抽取测试。"""

from app.agent.auxiliary_extractor import extract_auxiliary_operations


def test_extract_auxiliary_operations_from_cut_length_sentence():
    result = extract_auxiliary_operations(
        "【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。\n下面证明..."
    )

    operations = result["operations"]
    assert [op["type"] for op in operations] == [
        "construct_point_on_ray_with_distance",
        "connect",
        "connect",
    ]
    assert operations[0]["params"] == {
        "ray": "AE",
        "base_point": "E",
        "distance_ref": "AE",
        "new_point": "F",
    }
    assert operations[1]["params"] == {"points": ["C", "F"]}
    assert operations[2]["params"] == {"points": ["B", "F"]}
    assert all(op["source_sentence"] == "延长 AE 至点 F，使 EF = AE，连接 CF、BF。" for op in operations)


def test_extract_auxiliary_operations_ignores_non_auxiliary_text():
    result = extract_auxiliary_operations("证明中我们会连接 CF，但这里不是辅助线句。")

    assert result["operations"] == []
    assert result["warnings"] == []


def test_extract_auxiliary_operations_supports_intersection_and_midpoint():
    result = extract_auxiliary_operations("【辅助线】取 AB 的中点 M，AE 与 CD 交于 H。")

    operations = result["operations"]
    assert [op["type"] for op in operations] == ["midpoint", "intersection"]
    assert operations[0]["params"] == {"segment": "AB", "new_point": "M"}
    assert operations[1]["params"] == {"a": "AE", "b": "CD", "new_point": "H"}


def test_extract_auxiliary_operations_supports_perpendicular_foot_sentence():
    result = extract_auxiliary_operations("【辅助线】过点B作BF⊥AH交直线AH于点F。")

    operations = result["operations"]
    assert [op["type"] for op in operations] == ["construct_perpendicular"]
    assert operations[0]["params"] == {
        "point": "B",
        "line": "AH",
        "foot": "F",
        "segment": "BF",
    }


def test_extract_auxiliary_operations_normalizes_latex_perp_sentence():
    result = extract_auxiliary_operations(
        "【辅助线】过点 $C$ 作 $CF \\perp CH$ 交 $BH$ 于点 $F$，在 $BH$ 上截取 $BG = AH$，连接 $CG$。"
    )

    operations = result["operations"]
    assert [op["type"] for op in operations] == [
        "construct_perpendicular_intersection",
        "construct_point_on_ray_with_distance",
        "connect",
    ]
    assert operations[0]["params"] == {
        "point": "C",
        "line": "CH",
        "intersect_line": "BH",
        "foot": "F",
        "segment": "CF",
    }
    assert operations[1]["params"] == {
        "ray": "BH",
        "base_point": "B",
        "distance_ref": "AH",
        "new_point": "G",
    }
    assert operations[2]["params"] == {"points": ["C", "G"]}


def test_extract_auxiliary_operations_supports_perpendicular_intersection_sentence():
    result = extract_auxiliary_operations("【辅助线】过点 B 作 BF ⟂ BC 交 CH 的延长线于点 F，连接 AF。")

    operations = result["operations"]
    assert [op["type"] for op in operations] == ["connect"]
    assert operations[0]["params"] == {"points": ["A", "F"]}


def test_extract_auxiliary_operations_supports_unmarked_cut_length_sentence():
    result = extract_auxiliary_operations("观察 H,A,E 共线，试着在 BH 上截取一点 F，使 HF=AH。")

    operations = result["operations"]
    assert [op["type"] for op in operations] == ["construct_point_on_ray_with_distance"]
    assert operations[0]["params"] == {
        "ray": "HB",
        "base_point": "H",
        "distance_ref": "AH",
        "new_point": "F",
    }


def test_extract_auxiliary_operations_uses_text_fallback_when_rules_fail():
    def fallback(sentence):
        assert sentence == "作一条符合题意的特殊辅助线。"
        return [
            {
                "type": "connect",
                "params": {"points": ["A", "B"]},
                "confidence": 0.6,
            }
        ]

    result = extract_auxiliary_operations("【辅助线】作一条符合题意的特殊辅助线。", fallback_parser=fallback)

    assert result["operations"][0]["type"] == "connect"
    assert result["operations"][0]["source_sentence"] == "作一条符合题意的特殊辅助线。"
    assert result["operations"][0]["confidence"] == 0.6
    assert result["warnings"][0]["code"] == "fallback_parser_used"
