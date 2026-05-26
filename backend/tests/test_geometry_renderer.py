# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""受控几何渲染器测试。"""

from app.agent.geometry_renderer import build_geometry_figure_request


def test_build_geometry_figure_request_generates_controlled_matplotlib_code():
    scene = {
        "version": "1.0",
        "observations": {
            "points": [
                {"id": "A", "coordinate": [0, 0]},
                {"id": "E", "coordinate": [1, 0]},
                {"id": "C", "coordinate": [0, 1]},
                {"id": "B", "coordinate": [1, 1]},
            ],
            "drawn_segments": [
                {"endpoints": ["A", "E"]},
                {"endpoints": ["C", "B"]},
            ],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
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
    ]

    request = build_geometry_figure_request(scene, operations, session_id="session-1")

    assert request.session_id == "session-1"
    assert request.width == 800
    assert request.height == 600
    assert "plt.axis('off')" in request.code or 'plt.axis("off")' in request.code
    assert "set_aspect" in request.code
    assert "linestyle='--'" in request.code or 'linestyle="--"' in request.code
    assert "color='red'" in request.code or 'color="red"' in request.code
    assert "savefig" not in request.code
    assert "open(" not in request.code


def test_build_geometry_figure_request_generates_schematic_layout_without_coordinates():
    scene = {
        "version": "1.0",
        "observations": {
            "points": [{"id": "A"}, {"id": "E"}, {"id": "C"}],
            "drawn_segments": [{"endpoints": ["A", "E"]}],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
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
            "source_sentence": "延长 AE 至点 F，使 EF = AE。",
        }
    ]

    request = build_geometry_figure_request(scene, operations)

    assert "points = {" in request.code
    assert "'F':" in request.code
    assert "linestyle='--'" in request.code


def test_build_geometry_figure_request_renders_perpendicular_foot():
    scene = {
        "version": "1.0",
        "observations": {
            "points": [
                {"id": "A", "coordinate": [0, 0]},
                {"id": "H", "coordinate": [2, 0]},
                {"id": "B", "coordinate": [1, 1]},
            ],
            "drawn_segments": [{"endpoints": ["A", "H"]}],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
    operations = [
        {
            "id": "aux_1",
            "type": "construct_perpendicular",
            "params": {"point": "B", "line": "AH", "foot": "F", "segment": "BF"},
            "source_sentence": "过点B作BF⊥AH交直线AH于点F。",
        }
    ]

    request = build_geometry_figure_request(scene, operations)

    assert "'F': (1.0, 0.0)" in request.code
    assert "['B', 'F']" in request.code
    assert "linestyle='--'" in request.code


def test_build_geometry_figure_request_renders_perpendicular_intersection():
    scene = {
        "version": "1.0",
        "observations": {
            "points": [
                {"id": "C", "coordinate": [0, 1]},
                {"id": "H", "coordinate": [0, 2]},
                {"id": "B", "coordinate": [2, 0]},
            ],
            "drawn_segments": [{"endpoints": ["C", "H"]}, {"endpoints": ["B", "H"]}],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
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
            "source_sentence": "过点 C 作 CF⊥CH 交 BH 于点 F。",
        }
    ]

    request = build_geometry_figure_request(scene, operations)

    assert "'F': (1.0, 1.0)" in request.code
    assert "['C', 'F']" in request.code
    assert "linestyle='--'" in request.code


def test_build_geometry_figure_request_renders_cut_length_segment():
    scene = {
        "version": "1.0",
        "observations": {
            "points": [
                {"id": "B", "coordinate": [0, 0]},
                {"id": "H", "coordinate": [2, 0]},
                {"id": "A", "coordinate": [1, 1]},
            ],
            "drawn_segments": [{"endpoints": ["B", "H"]}],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
    operations = [
        {
            "id": "aux_1",
            "type": "construct_point_on_ray_with_distance",
            "params": {
                "ray": "HB",
                "base_point": "H",
                "distance_ref": "AH",
                "new_point": "F",
            },
            "source_sentence": "观察 H,A,E 共线，试着在 BH 上截取一点 F，使 HF=AH。",
        }
    ]

    request = build_geometry_figure_request(scene, operations)

    assert "'F':" in request.code
    assert "['H', 'F']" in request.code
    assert "linestyle='--'" in request.code


def test_build_geometry_figure_request_places_cut_point_away_from_base_on_segment():
    scene = {
        "version": "1.0",
        "observations": {
            "points": [
                {"id": "B", "coordinate": [0, 0]},
                {"id": "H", "coordinate": [2, 0]},
                {"id": "A", "coordinate": [1, 1]},
            ],
            "drawn_segments": [{"endpoints": ["B", "H"]}],
        },
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
    operations = [
        {
            "id": "aux_1",
            "type": "construct_point_on_ray_with_distance",
            "params": {
                "ray": "BH",
                "base_point": "B",
                "distance_ref": "AH",
                "new_point": "G",
            },
            "source_sentence": "在 BH 上截取 BG = AH。",
        }
    ]

    request = build_geometry_figure_request(scene, operations)

    assert "'G': (1.4142135623730951, 0.0)" in request.code
    assert "['B', 'G']" in request.code


def test_build_geometry_figure_request_fails_when_position_cannot_be_inferred():
    scene = {
        "version": "1.0",
        "observations": {"points": [{"id": "A"}], "drawn_segments": []},
        "given_relations": [],
        "warnings": [],
        "uncertain": [],
    }
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
            "source_sentence": "延长 AE 至点 F，使 EF = AE。",
        }
    ]

    try:
        build_geometry_figure_request(scene, operations)
    except ValueError as exc:
        assert "cannot infer point coordinates" in str(exc)
    else:
        raise AssertionError("expected ValueError")
