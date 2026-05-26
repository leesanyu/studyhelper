# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""原图 overlay 辅助线渲染测试。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from PIL import ImageDraw

from app.agent.figure_overlay import (
    OverlayRenderError,
    build_overlay_plan_from_auxiliary_text,
    infer_layout_crop_box,
    inspect_overlay_semantics,
    render_overlay_plan,
    snap_localized_points_to_geometry,
)
from app.services.assets import InMemoryAssetRepository
from app.services.storage import LocalAssetStorage


def _base_image(path):
    image = Image.new("RGB", (320, 220), "white")
    image.save(path)


def test_snap_localized_points_moves_label_coordinate_to_geometry_vertex(tmp_path):
    """VLM 坐标落在字母附近时，应吸附到附近线段交汇的几何顶点。"""
    image_path = tmp_path / "crop.png"
    image = Image.new("RGB", (220, 180), "white")
    draw = ImageDraw.Draw(image)
    vertex = (90, 82)
    draw.line([vertex, (28, 150)], fill="black", width=4)
    draw.line([vertex, (172, 145)], fill="black", width=4)
    draw.line([vertex, (142, 22)], fill="black", width=4)
    draw.text((106, 28), "C", fill="black")
    image.save(image_path)

    result = snap_localized_points_to_geometry(
        image_path,
        {"C": {"x": 118, "y": 40, "confidence": 0.95}},
        search_radius=58,
    )

    snapped = result["points"]["C"]
    assert abs(snapped["x"] - vertex[0]) <= 5
    assert abs(snapped["y"] - vertex[1]) <= 5
    assert result["raw_points"]["C"]["x"] == 118
    assert result["adjustments"]["C"]["snapped"] is True
    assert result["adjustments"]["C"]["snap_confidence"] > 0


def test_snap_localized_points_prefers_geometry_component_over_isolated_label(tmp_path):
    """字母笔画形成强局部结构时，仍应优先吸附到几何线段连通域。"""
    image_path = tmp_path / "e_label.png"
    image = Image.new("RGB", (240, 210), "white")
    draw = ImageDraw.Draw(image)
    vertex = (115, 105)
    draw.line([(20, 25), vertex, (20, 190)], fill="black", width=4)
    draw.line([vertex, (220, 190)], fill="black", width=4)
    draw.line([(165, 45), (165, 83)], fill="black", width=6)
    draw.line([(165, 45), (193, 45)], fill="black", width=6)
    draw.line([(165, 64), (189, 64)], fill="black", width=6)
    draw.line([(165, 83), (193, 83)], fill="black", width=6)
    image.save(image_path)

    result = snap_localized_points_to_geometry(
        image_path,
        {"E": {"x": 178, "y": 65, "confidence": 0.9}},
        search_radius=95,
    )

    snapped = result["points"]["E"]
    assert abs(snapped["x"] - vertex[0]) <= 6
    assert abs(snapped["y"] - vertex[1]) <= 6


def test_snap_localized_points_uses_skeleton_junction_for_dense_convergence(tmp_path):
    """多条粗线密集汇聚时，应吸附到中心线骨架顶点，而不是墨迹团块内部。"""
    image_path = tmp_path / "dense_junction.png"
    image = Image.new("RGB", (220, 180), "white")
    draw = ImageDraw.Draw(image)
    vertex = (100, 75)
    for endpoint in [(20, 160), (105, 170), (190, 95), (190, 130), (125, 30)]:
        draw.line([vertex, endpoint], fill="black", width=8)
    image.save(image_path)

    result = snap_localized_points_to_geometry(
        image_path,
        {"C": {"x": 96, "y": 42, "confidence": 0.9}},
        search_radius=70,
    )

    snapped = result["points"]["C"]
    assert abs(snapped["x"] - vertex[0]) <= 6
    assert abs(snapped["y"] - vertex[1]) <= 6


def test_snap_localized_points_corrects_low_resolution_c_vertex_from_web_crop(tmp_path):
    """正式上传低分辨率 crop 下，C 点仍应靠近多线汇聚顶点。"""
    source = Path(__file__).resolve().parents[2] / "tests" / "questions" / "几何-线段-全等.jpg"
    image = Image.open(source).convert("RGB")
    scale = 1600 / max(image.size)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    page_path = tmp_path / "web_upload.jpg"
    resized.save(page_path, format="JPEG", quality=85)
    crop_box = infer_layout_crop_box(page_path, target_label="图2")
    assert crop_box is not None
    crop_path = tmp_path / "web_crop.png"
    resized.crop(tuple(crop_box)).save(crop_path)

    result = snap_localized_points_to_geometry(
        crop_path,
        {"C": {"x": 168, "y": 74, "confidence": 0.95}},
        search_radius=42,
    )

    snapped = result["points"]["C"]
    assert abs(snapped["x"] - 190) <= 8
    assert abs(snapped["y"] - 87) <= 8


def test_snap_localized_points_ignores_large_letter_e_component_in_high_resolution_crop(tmp_path):
    """高分辨率 Web crop 中，E 点不应被吸附到右侧字母 E 笔画上。"""
    source = Path(__file__).resolve().parents[2] / "tests" / "questions" / "几何-线段-全等.jpg"
    image = Image.open(source).convert("RGB")
    page_path = tmp_path / "web_upload.jpg"
    image.save(page_path, format="JPEG", quality=92)
    crop_box = infer_layout_crop_box(page_path, target_label="图2")
    assert crop_box is not None
    crop_path = tmp_path / "web_crop.png"
    image.crop(tuple(crop_box)).save(crop_path)

    result = snap_localized_points_to_geometry(
        crop_path,
        {"E": {"x": 656, "y": 288, "confidence": 0.95}},
        search_radius=42,
    )

    snapped = result["points"]["E"]
    assert snapped["x"] <= 675
    assert 270 <= snapped["y"] <= 295


def test_snap_localized_points_keeps_raw_coordinate_when_no_geometry_candidate(tmp_path):
    """没有可靠线条候选时，不阻断流程，保留 VLM 原坐标。"""
    image_path = tmp_path / "blank.png"
    Image.new("RGB", (120, 100), "white").save(image_path)

    result = snap_localized_points_to_geometry(
        image_path,
        {"A": {"x": 40, "y": 50, "confidence": 0.7}},
        search_radius=30,
    )

    assert result["points"]["A"]["x"] == 40
    assert result["points"]["A"]["y"] == 50
    assert result["adjustments"]["A"]["snapped"] is False
    assert "point_snap_no_candidate:A" in result["warnings"]


def test_infer_layout_crop_box_selects_second_diagram_for_figure_2(tmp_path):
    image_path = tmp_path / "page.png"
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    for offset in (120, 380, 650):
        draw.line([(offset, 330), (offset + 90, 220), (offset + 180, 330), (offset, 330)], fill="black", width=4)
        draw.line([(offset + 80, 330), (offset + 120, 420)], fill="black", width=4)
    image.save(image_path)

    crop_box = infer_layout_crop_box(image_path, target_label="图2")

    assert crop_box is not None
    assert crop_box[0] < 380 < crop_box[2]
    assert crop_box[0] > 250
    assert crop_box[2] < 620


def test_infer_layout_crop_box_matches_validated_question_fixture_for_figure_2():
    """真实题图应恢复 demo 验证过的稳定图2裁剪框。"""
    image_path = Path(__file__).resolve().parents[2] / "tests" / "questions" / "几何-线段-全等.jpg"

    crop_box = infer_layout_crop_box(image_path, target_label="图2")

    assert crop_box is not None
    left, top, right, bottom = crop_box
    assert abs(left - 1260) <= 12
    assert abs(top - 823) <= 12
    assert abs(right - 2090) <= 12
    assert abs(bottom - 1655) <= 12


@pytest.mark.asyncio
async def test_render_overlay_plan_places_point_on_directed_ray_and_persists(tmp_path):
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    repository = InMemoryAssetRepository()

    result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "coordinate_space": "crop_pixels",
            "constructions": [
                {
                    "op": "point_on_segment_by_distance",
                    "point": "F",
                    "ray": "AE",
                    "from": "A",
                    "distance": "2*AE",
                    "role": "construction",
                },
                {"op": "connect_points", "points": ["C", "F"], "role": "construction"},
                {"op": "connect_points", "points": ["B", "F"], "role": "construction"},
            ],
        },
        localized_points={
            "A": {"x": 80, "y": 120, "confidence": 0.95},
            "E": {"x": 150, "y": 120, "confidence": 0.95},
            "C": {"x": 90, "y": 40, "confidence": 0.95},
            "B": {"x": 230, "y": 60, "confidence": 0.95},
        },
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
        session_id="session-1",
        message_id="message-1",
        display_scale=2,
    )

    computed_f = result["computed_points"]["F"]
    assert computed_f["x"] == 220
    assert computed_f["y"] == 120
    assert result["image_url"].startswith("/assets/figures/")
    stored_asset = repository.assets[result["asset_id"]]
    assert stored_asset["asset_type"] == "figure_overlay"
    assert stored_asset["session_id"] == "session-1"
    assert stored_asset["message_id"] == "message-1"
    assert stored_asset["width"] == 640
    assert stored_asset["height"] == 440
    assert (tmp_path / stored_asset["object_key"]).exists()


@pytest.mark.asyncio
async def test_render_overlay_plan_draws_auxiliary_lines_thick_enough(tmp_path):
    """辅助线需要足够粗，缓解轻微点位偏差带来的视觉割裂。"""
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    repository = InMemoryAssetRepository()

    result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "constructions": [
                {"op": "connect_points", "points": ["A", "B"], "role": "construction"},
            ],
        },
        localized_points={
            "A": {"x": 80, "y": 100, "confidence": 0.95},
            "B": {"x": 240, "y": 100, "confidence": 0.95},
        },
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
        display_scale=2,
    )

    stored_asset = repository.assets[result["asset_id"]]
    rendered = Image.open(tmp_path / stored_asset["object_key"]).convert("RGBA")
    x = 160 * 2
    red_rows = [
        y for y in range(rendered.height)
        if rendered.getpixel((x, y))[0] > 160 and rendered.getpixel((x, y))[1] < 90
    ]

    assert max(red_rows) - min(red_rows) + 1 >= 8


@pytest.mark.asyncio
async def test_render_overlay_plan_draws_constructed_point_label_readably(tmp_path):
    """新构造点标签需要更大且有描边，避免在原图上显得过细。"""
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    repository = InMemoryAssetRepository()

    result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "constructions": [
                {
                    "op": "point_on_segment_by_distance",
                    "point": "F",
                    "ray": "AE",
                    "from": "A",
                    "distance": "2*AE",
                },
            ],
        },
        localized_points={
            "A": {"x": 80, "y": 120},
            "E": {"x": 150, "y": 120},
        },
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
        display_scale=2,
    )

    stored_asset = repository.assets[result["asset_id"]]
    rendered = Image.open(tmp_path / stored_asset["object_key"]).convert("RGBA")
    computed_f = result["computed_points"]["F"]
    label_left = int((computed_f["x"] + 5) * 2)
    label_top = int((computed_f["y"] - 22) * 2)
    label_box = rendered.crop((label_left, label_top, label_left + 44, label_top + 46))
    red_coords = [
        (index % label_box.width, index // label_box.width)
        for index, pixel in enumerate(label_box.getdata())
        if pixel[0] > 130 and pixel[1] < 95 and pixel[2] < 95
    ]

    assert len(red_coords) >= 150
    assert max(x for x, _ in red_coords) - min(x for x, _ in red_coords) + 1 >= 14
    assert max(y for _, y in red_coords) - min(y for _, y in red_coords) + 1 >= 24


@pytest.mark.asyncio
async def test_render_overlay_plan_keeps_ray_direction_semantics(tmp_path):
    image_path = tmp_path / "crop.png"
    _base_image(image_path)

    ae_result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "constructions": [
                {
                    "op": "point_on_segment_by_distance",
                    "point": "F",
                    "ray": "AE",
                    "from": "A",
                    "distance": "2*AE",
                }
            ],
        },
        localized_points={
            "A": {"x": 80, "y": 120},
            "E": {"x": 150, "y": 120},
        },
        display_scale=1,
    )
    ea_result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "constructions": [
                {
                    "op": "point_on_segment_by_distance",
                    "point": "F",
                    "ray": "EA",
                    "from": "E",
                    "distance": "2*AE",
                }
            ],
        },
        localized_points={
            "A": {"x": 80, "y": 120},
            "E": {"x": 150, "y": 120},
        },
        display_scale=1,
    )

    assert ae_result["computed_points"]["F"]["x"] > 150
    assert ea_result["computed_points"]["F"]["x"] < 80


@pytest.mark.asyncio
async def test_render_overlay_plan_draws_extension_segment_for_constructed_point(tmp_path):
    """构造射线新点时，应把 from 点到新点的延长线段画出来。"""
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    repository = InMemoryAssetRepository()

    result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "constructions": [
                {
                    "op": "point_on_segment_by_distance",
                    "point": "F",
                    "ray": "EA",
                    "from": "A",
                    "distance": "AE",
                }
            ],
        },
        localized_points={
            "A": {"x": 150, "y": 120},
            "E": {"x": 220, "y": 80},
        },
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
        display_scale=1,
    )

    stored_asset = repository.assets[result["asset_id"]]
    rendered_path = tmp_path / stored_asset["object_key"]
    with Image.open(rendered_path).convert("RGB") as image:
        # A=(150,120), F=(80,160)，该点落在 AF 的第二段虚线内。
        r, g, b = image.getpixel((125, 134))

    assert r > 180
    assert g < 120
    assert b < 120


def test_build_overlay_plan_from_perpendicular_auxiliary_text():
    plan = build_overlay_plan_from_auxiliary_text(
        "过点 $C$ 作 $CK \\perp CE$，且使 $CK = CE$（点 $K$ 与点 $B$ 位于直线 $CE$ 同侧），连接 $BK$、$KH$。"
    )

    assert plan is not None
    assert plan["plan_type"] == "overlay_on_crop"
    assert plan["constructions"][0] == {
        "op": "point_on_perpendicular_by_distance",
        "point": "K",
        "vertex": "C",
        "perpendicular_to": "CE",
        "distance": "CE",
        "side_reference": "B",
    }
    assert {"op": "connect_points", "points": ["B", "K"]} in plan["constructions"]
    assert {"op": "connect_points", "points": ["H", "K"]} in plan["constructions"]


@pytest.mark.asyncio
async def test_render_overlay_plan_constructs_point_on_perpendicular_with_distance(tmp_path):
    image_path = tmp_path / "crop.png"
    _base_image(image_path)

    result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan={
            "plan_type": "overlay_on_crop",
            "constructions": [
                {
                    "op": "point_on_perpendicular_by_distance",
                    "point": "K",
                    "vertex": "C",
                    "perpendicular_to": "CE",
                    "distance": "CE",
                    "side_reference": "B",
                }
            ],
        },
        localized_points={
            "C": {"x": 100, "y": 100},
            "E": {"x": 200, "y": 100},
            "B": {"x": 150, "y": 220},
        },
    )

    computed_k = result["computed_points"]["K"]
    assert abs(computed_k["x"] - 100) <= 1
    assert abs(computed_k["y"] - 200) <= 1


@pytest.mark.asyncio
async def test_inspect_overlay_semantics_detects_wrong_perpendicular_construction(tmp_path):
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    bad_plan = {
        "plan_type": "overlay_on_crop",
        "constructions": [
            {
                "op": "point_on_segment_by_distance",
                "point": "K",
                "ray": "CE",
                "from": "C",
                "distance": "CE",
            },
            {"op": "connect_points", "points": ["B", "K"]},
            {"op": "connect_points", "points": ["K", "H"]},
        ],
    }
    localized_points = {
        "C": {"x": 100, "y": 100},
        "E": {"x": 200, "y": 100},
        "B": {"x": 150, "y": 220},
        "H": {"x": 240, "y": 220},
    }
    render_result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan=bad_plan,
        localized_points=localized_points,
    )

    observation = inspect_overlay_semantics(
        overlay_plan=bad_plan,
        localized_points=localized_points,
        render_result=render_result,
        auxiliary_text="过点 C 作 CK⊥CE，且使 CK=CE，连接 BK、KH。",
    )

    assert observation is not None
    assert any(
        "CK" in item and "CE" in item and "垂直" in item
        for item in observation["semantic_programmatic"]["wrong"]
    )


@pytest.mark.asyncio
async def test_inspect_overlay_semantics_requests_revision_for_missing_connection(tmp_path):
    """语义检查发现漏画辅助线时，应要求修正而不是阻断展示。"""
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    overlay_plan = {
        "plan_type": "overlay_on_crop",
        "constructions": [
            {
                "op": "point_on_segment_by_distance",
                "point": "F",
                "ray": "AE",
                "from": "A",
                "distance": "2*AE",
            },
            {"op": "connect_points", "points": ["C", "F"]},
            {"op": "unsupported_note", "points": ["B", "F"]},
        ],
    }
    localized_points = {
        "A": {"x": 80, "y": 120},
        "E": {"x": 150, "y": 120},
        "C": {"x": 90, "y": 40},
        "B": {"x": 230, "y": 60},
    }
    render_result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan=overlay_plan,
        localized_points=localized_points,
    )

    observation = inspect_overlay_semantics(
        overlay_plan=overlay_plan,
        localized_points=localized_points,
        render_result=render_result,
        figure_goal={"expected_auxiliary": ["connect CF", "connect BF"]},
        auxiliary_text="延长 AE 至点 F，使 EF=AE，连接 CF、BF。",
    )

    assert observation is not None
    assert observation["next_action"] == "revise_code"
    assert any("BF" in item for item in observation["semantic_programmatic"]["missing"])
    assert observation["semantic_programmatic"]["warnings"]


@pytest.mark.asyncio
async def test_inspect_overlay_semantics_detects_wrong_equal_length_constraint(tmp_path):
    """语义检查发现 EF=AE 被画成 AF=AE 时，应给出可修正 Observation。"""
    image_path = tmp_path / "crop.png"
    _base_image(image_path)
    overlay_plan = {
        "plan_type": "overlay_on_crop",
        "constructions": [
            {
                "op": "point_on_segment_by_distance",
                "point": "F",
                "ray": "AE",
                "from": "A",
                "distance": "AE",
            },
            {"op": "connect_points", "points": ["C", "F"]},
            {"op": "connect_points", "points": ["B", "F"]},
        ],
    }
    localized_points = {
        "A": {"x": 80, "y": 120},
        "E": {"x": 150, "y": 120},
        "C": {"x": 90, "y": 40},
        "B": {"x": 230, "y": 60},
    }
    render_result = await render_overlay_plan(
        image_path=image_path,
        overlay_plan=overlay_plan,
        localized_points=localized_points,
    )

    observation = inspect_overlay_semantics(
        overlay_plan=overlay_plan,
        localized_points=localized_points,
        render_result=render_result,
        figure_goal={"expected_auxiliary": ["F lies on ray AE", "connect CF", "connect BF"]},
        auxiliary_text="延长 AE 至点 F，使 EF=AE，连接 CF、BF。",
    )

    assert observation is not None
    assert observation["next_action"] == "revise_code"
    assert any("EF" in item and "AE" in item for item in observation["semantic_programmatic"]["wrong"])
    assert any("E 外侧" in item for item in observation["semantic_programmatic"]["wrong"])


@pytest.mark.asyncio
async def test_render_overlay_plan_reports_missing_point_as_observation(tmp_path):
    image_path = tmp_path / "crop.png"
    _base_image(image_path)

    with pytest.raises(OverlayRenderError) as exc_info:
        await render_overlay_plan(
            image_path=image_path,
            overlay_plan={
                "plan_type": "overlay_on_crop",
                "constructions": [
                    {"op": "connect_points", "points": ["C", "F"], "role": "construction"}
                ],
            },
            localized_points={"C": {"x": 90, "y": 40}},
        )

    assert exc_info.value.observation["next_action"] == "revise_code"
    assert "F" in exc_info.value.observation["execution"]["error"]


@pytest.mark.asyncio
async def test_render_overlay_plan_rejects_plan_without_supported_operations(tmp_path):
    image_path = tmp_path / "crop.png"
    _base_image(image_path)

    with pytest.raises(OverlayRenderError) as exc_info:
        await render_overlay_plan(
            image_path=image_path,
            overlay_plan={
                "plan_type": "overlay_on_crop",
                "constructions": [
                    {"type": "point", "name": "F", "construction": "extend AE"},
                    {"type": "segment", "points": ["C", "F"]},
                ],
            },
            localized_points={
                "A": {"x": 80, "y": 120},
                "E": {"x": 150, "y": 120},
                "C": {"x": 90, "y": 40},
            },
        )

    assert exc_info.value.observation["next_action"] == "revise_code"
    assert "unsupported overlay operations" in exc_info.value.observation["execution"]["error"]
