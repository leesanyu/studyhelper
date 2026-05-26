# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""几何辅助操作校验测试。"""

from app.agent.geometry_validator import validate_geometry_operations


def _scene():
    return {
        "version": "1.0",
        "observations": {
            "points": [{"id": point} for point in ["A", "B", "C", "D", "E", "H"]],
            "drawn_segments": [
                {"endpoints": ["A", "E"]},
                {"endpoints": ["C", "F"]},
            ],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }


def test_validate_geometry_operations_accepts_unique_constructed_point_then_connections():
    operations = [
        {
            "id": "aux_1",
            "type": "construct_point_on_ray_with_distance",
            "params": {
                "ray": "AE",
                "base_point": "E",
                "distance_ref": "AE",
                "new_point": "F",
            },
            "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
        },
        {
            "id": "aux_2",
            "type": "connect",
            "params": {"points": ["C", "F"]},
            "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
        },
        {
            "id": "aux_3",
            "type": "connect",
            "params": {"points": ["B", "F"]},
            "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
        },
    ]

    result = validate_geometry_operations(_scene(), operations)

    assert result["ok"] is True
    assert [op["id"] for op in result["accepted_operations"]] == ["aux_1", "aux_2", "aux_3"]
    assert result["rejected_operations"] == []


def test_validate_geometry_operations_accepts_later_operation_referencing_constructed_point():
    operations = [
        {
            "id": "aux_1",
            "type": "construct_perpendicular",
            "params": {"point": "B", "line": "AH", "foot": "F", "segment": "BF"},
            "source_sentence": "过点B作BF⊥AH于点F，过点C作CG⊥BF于点G。",
        },
        {
            "id": "aux_2",
            "type": "construct_perpendicular",
            "params": {"point": "C", "line": "BF", "foot": "G", "segment": "CG"},
            "source_sentence": "过点B作BF⊥AH于点F，过点C作CG⊥BF于点G。",
        },
    ]

    result = validate_geometry_operations(_scene(), operations)

    assert result["ok"] is True
    assert [op["id"] for op in result["accepted_operations"]] == ["aux_1", "aux_2"]
    assert result["rejected_operations"] == []


def test_validate_geometry_operations_accepts_perpendicular_intersection_then_connection():
    operations = [
        {
            "id": "aux_1",
            "type": "construct_perpendicular_intersection",
            "params": {
                "point": "C",
                "line": "CH",
                "intersect_line": "BH",
                "foot": "F",
                "segment": "CF",
            },
            "source_sentence": "过点 C 作 CF⊥CH 交 BH 于点 F，连接 CF。",
        },
        {
            "id": "aux_2",
            "type": "connect",
            "params": {"points": ["C", "F"]},
            "source_sentence": "过点 C 作 CF⊥CH 交 BH 于点 F，连接 CF。",
        },
    ]

    result = validate_geometry_operations(_scene(), operations)

    assert result["ok"] is True
    assert [op["id"] for op in result["accepted_operations"]] == ["aux_1", "aux_2"]
    assert result["rejected_operations"] == []


def test_validate_geometry_operations_rejects_unknown_existing_point():
    operations = [
        {
            "id": "aux_1",
            "type": "connect",
            "params": {"points": ["C", "X"]},
            "source_sentence": "连接 CX。",
        }
    ]

    result = validate_geometry_operations(_scene(), operations)

    assert result["ok"] is False
    assert result["code"] == "geometry_check_failed"
    assert result["rejected_operations"][0]["operation_id"] == "aux_1"
    assert "unknown point X" in result["rejected_operations"][0]["reason"]


def test_validate_geometry_operations_rejects_duplicate_new_point_construction():
    operations = [
        {
            "id": "aux_1",
            "type": "extend_line",
            "params": {"line": "AE", "through": "E", "new_point": "F"},
            "source_sentence": "延长 AE 至点 F。",
        },
        {
            "id": "aux_2",
            "type": "construct_point_on_ray_with_distance",
            "params": {
                "ray": "AE",
                "base_point": "E",
                "distance_ref": "AE",
                "new_point": "F",
            },
            "source_sentence": "延长 AE 至点 F，使 EF = AE。",
        },
    ]

    result = validate_geometry_operations(_scene(), operations)

    assert result["ok"] is False
    assert "duplicate construction for new point F" in result["rejected_operations"][0]["reason"]


def test_validate_geometry_operations_marks_visual_review_for_uncertain_direction():
    scene = _scene()
    scene["uncertain"] = [{"type": "point_order", "message": "A/E 点序不确定"}]
    operations = [
        {
            "id": "aux_1",
            "type": "extend_line",
            "params": {"line": "AE", "through": "E", "new_point": "F"},
            "source_sentence": "延长 AE 至点 F。",
        }
    ]

    result = validate_geometry_operations(scene, operations)

    assert result["ok"] is True
    assert result["needs_visual_review"] is True
    assert result["warnings"][0]["code"] == "visual_review_recommended"
