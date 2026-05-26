# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""规划层和执行层逻辑。

规划层：非流式调用 LLM，输出结构化计划 {question_type, strategy, tool_calls, need_deep_reflexion}。
执行层：流式调用 LLM，根据 strategy 生成教学回复，支持实时 delta 回调。
"""

from __future__ import annotations

import base64
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from app.agent.llm_client import LLMClient, StreamEvent, TextDelta
from app.agent.prompts import (
    build_figure_overlay_draw_messages,
    build_figure_overlay_revision_messages,
    build_figure_draw_messages,
    build_figure_goal_messages,
    build_figure_revision_messages,
    build_figure_semantic_inspection_messages,
    build_figure_trigger_messages,
    build_point_location_messages,
    build_planning_messages,
    build_solving_messages,
    build_target_crop_messages,
)


# ── 规划层输出类型 ──────────────────────────────────────────────


@dataclass(frozen=True)
class PlanResult:
    """规划层输出，决定编排层的后续行为。"""

    question_type: str
    strategy: str
    tool_calls: list[str]
    need_deep_reflexion: bool = False
    usage: dict[str, int] | None = None


# 规划层默认 fallback（JSON 解析失败时使用）
_DEFAULT_PLAN = PlanResult(
    question_type="continue_dialogue",
    strategy="socratic_guide",
    tool_calls=[],
    need_deep_reflexion=False,
)


# ── 规划层 ───────────────────────────────────────────────────────


async def plan(
    llm_client: LLMClient,
    *,
    user_message: str,
    image_summary: str | None = None,
    chat_history: list[dict] | None = None,
    current_question: str | None = None,
    current_knowledge: str | None = None,
    current_diagram: str | None = None,
) -> PlanResult:
    """调用规划层 LLM，分析用户消息并输出结构化计划。

    启用 JSON Mode 保证输出格式。解析失败则 fallback 为默认策略。
    """
    messages = build_planning_messages(
        user_message=user_message,
        image_summary=image_summary,
        chat_history=chat_history,
        current_question=current_question,
        current_knowledge=current_knowledge,
        current_diagram=current_diagram,
    )

    response = await llm_client.chat_json(messages=messages, scene="planning")

    try:
        data = json.loads(response.content)
        return PlanResult(
            question_type=str(data.get("question_type", _DEFAULT_PLAN.question_type)),
            strategy=str(data.get("strategy", _DEFAULT_PLAN.strategy)),
            tool_calls=list(data.get("tool_calls", [])),
            need_deep_reflexion=bool(data.get("need_deep_reflexion", False)),
            usage=response.usage or {},
        )
    except (json.JSONDecodeError, TypeError, KeyError):
        return _DEFAULT_PLAN


# ── 执行层 ───────────────────────────────────────────────────────


@dataclass
class SolveResult:
    """执行层输出，包含完整缓冲内容和解析后的 figure 代码块。"""

    content: str
    figure_blocks: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


# python:figure 代码块正则
_FIGURE_BLOCK_RE = re.compile(
    r"```python:figure\s*\n(.*?)```", re.DOTALL
)
_PYTHON_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _model_for_scene(llm_client: LLMClient, scene: str) -> str:
    getter = getattr(llm_client, "model_for_scene", None)
    if callable(getter):
        try:
            return str(getter(scene))
        except Exception:
            return ""
    return ""


async def solve(
    llm_client: LLMClient,
    *,
    strategy: str,
    user_message: str,
    image_summary: str | None = None,
    chat_history: list[dict] | None = None,
    current_question: str | None = None,
    current_knowledge: str | None = None,
    current_diagram: str | None = None,
    current_geometry: dict | None = None,
    tool_results: dict | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> SolveResult:
    """调用执行层 LLM，生成教学回复。

    流式收集输出，每个 TextDelta 同时通过 on_delta 回调实时通知编排层。
    仍返回完整 SolveResult，供 figure 解析和反思使用。
    """
    messages = build_solving_messages(
        strategy=strategy,
        user_message=user_message,
        image_summary=image_summary,
        chat_history=chat_history,
        current_question=current_question,
        current_knowledge=current_knowledge,
        current_diagram=current_diagram,
        current_geometry=current_geometry,
        tool_results=tool_results,
    )

    # 流式收集完整输出，同时通过回调实时转发
    chunks: list[str] = []
    usage: dict[str, int] = {}
    async for event in llm_client.stream_chat(messages=messages, scene="solving"):
        if isinstance(event, TextDelta):
            chunks.append(event.text)
            if on_delta is not None:
                on_delta(event.text)
        elif hasattr(event, "usage") and event.usage:
            usage = event.usage

    content = "".join(chunks)

    # 解析 python:figure 代码块
    figure_blocks = _FIGURE_BLOCK_RE.findall(content)

    return SolveResult(
        content=content,
        figure_blocks=figure_blocks,
        usage=usage,
    )


async def figure_trigger(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    existing_python_figure: str | None = None,
) -> dict[str, Any]:
    """调用 LLM 判断是否需要启动 Figure Agent。"""
    messages = build_figure_trigger_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        existing_python_figure=existing_python_figure,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="figure_trigger",
        temperature=0.1,
    )
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("figure_needed", False)
    data.setdefault("reason", "")
    data.setdefault("auxiliary_intent", "")
    data.setdefault("confidence", 0.0)
    data.setdefault("existing_python_figure", existing_python_figure or "")
    return data


async def figure_goal_check(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    visual_observation: dict | None,
    geometry_scene_candidate: dict | None,
    solve_content: str,
    auxiliary_intent: str | None,
    trigger: dict | None,
) -> dict[str, Any]:
    """调用 LLM 整理绘图目标。"""
    messages = build_figure_goal_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        visual_observation=visual_observation,
        geometry_scene_candidate=geometry_scene_candidate,
        solve_content=solve_content,
        auxiliary_intent=auxiliary_intent,
        trigger=trigger,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="figure_goal",
        temperature=0.1,
    )
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("goal_status", "needs_inference")
    data.setdefault("normalized_auxiliary_intent", auxiliary_intent or "")
    data.setdefault("expected_auxiliary", [])
    data.setdefault("original_figure_elements", [])
    data.setdefault("layout_hint", {})
    data.setdefault("style_requirements", {})
    data.setdefault("warnings", [])
    data["_llm"] = {
        "scene": "figure_goal",
        "model": _model_for_scene(llm_client, "figure_goal"),
    }
    return data


async def figure_draw_plan(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
) -> tuple[str, dict[str, Any]]:
    """调用 LLM 生成绘图代码，并做 best-effort 提取。"""
    messages = build_figure_draw_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
    )
    response = await llm_client.chat(
        messages=messages,
        scene="figure_draw",
        temperature=0.2,
    )
    code, warning = extract_figure_code(response.content)
    metadata: dict[str, Any] = {
        "raw_content": response.content,
        "warning": warning,
        "usage": response.usage,
        "scene": "figure_draw",
        "model": _model_for_scene(llm_client, "figure_draw"),
    }
    return code, metadata


async def figure_target_crop(
    llm_client: LLMClient,
    *,
    image_base64: str,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
) -> dict[str, Any]:
    """调用 Vision LLM 定位目标几何图裁剪框。"""
    messages = build_target_crop_messages(
        image_base64=image_base64,
        image_size=_image_size_from_base64(image_base64),
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="vision",
        temperature=0.1,
    )
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("label", "")
    data.setdefault("crop_box", [])
    data.setdefault("confidence", 0.0)
    data.setdefault("warnings", [])
    data["usage"] = response.usage
    data["scene"] = "vision"
    data["model"] = _model_for_scene(llm_client, "vision")
    return data


def _image_size_from_base64(image_base64: str) -> tuple[int, int] | None:
    try:
        raw = base64.b64decode(image_base64)
        with Image.open(io.BytesIO(raw)) as image:
            return image.size
    except Exception:
        return None


async def figure_point_location(
    llm_client: LLMClient,
    *,
    image_base64: str,
    point_labels: list[str],
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
) -> dict[str, Any]:
    """调用 Vision LLM 在裁剪图坐标系定位点位。"""
    messages = build_point_location_messages(
        image_base64=image_base64,
        image_size=_image_size_from_base64(image_base64),
        point_labels=point_labels,
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="vision",
        temperature=0.0,
    )
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    points = data.get("points")
    requested_labels = {str(label).upper() for label in point_labels}
    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
    filtered_points: dict[str, Any] = {}
    if isinstance(points, dict):
        for label, value in points.items():
            normalized_label = str(label).upper()
            if normalized_label in requested_labels:
                filtered_points[normalized_label] = value
            else:
                warnings.append(f"ignored_unrequested_point:{label}")
    data["points"] = filtered_points
    data["warnings"] = warnings
    data["usage"] = response.usage
    data["scene"] = "vision"
    data["model"] = _model_for_scene(llm_client, "vision")
    return data


async def figure_overlay_draw_plan(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    target_diagram: dict,
    localized_points: dict,
    auxiliary_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """调用 LLM 生成 overlay plan。"""
    messages = build_figure_overlay_draw_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
        target_diagram=target_diagram,
        localized_points=localized_points,
        auxiliary_text=auxiliary_text,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="figure_draw",
        temperature=0.2,
    )
    try:
        plan_data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        plan_data = {}
    if not isinstance(plan_data, dict):
        plan_data = {}
    metadata: dict[str, Any] = {
        "raw_content": response.content,
        "usage": response.usage,
        "scene": "figure_draw",
        "model": _model_for_scene(llm_client, "figure_draw"),
    }
    return plan_data, metadata


async def figure_overlay_revision_plan(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    target_diagram: dict,
    localized_points: dict,
    auxiliary_text: str,
    previous_plan: dict,
    observation: dict,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """调用 Revision LLM 修正 overlay plan。"""
    messages = build_figure_overlay_revision_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
        target_diagram=target_diagram,
        localized_points=localized_points,
        auxiliary_text=auxiliary_text,
        previous_plan=previous_plan,
        observation=observation,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="figure_revision",
        temperature=0.2,
    )
    try:
        plan_data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        plan_data = {}
    if not isinstance(plan_data, dict):
        plan_data = {}
    return plan_data, {
        "raw_content": response.content,
        "usage": response.usage,
        "scene": "figure_revision",
        "model": _model_for_scene(llm_client, "figure_revision"),
    }


async def figure_revision_plan(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    previous_code: str,
    observation: dict,
) -> tuple[str, dict[str, Any]]:
    """调用 Revision LLM 修正绘图代码。"""
    messages = build_figure_revision_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
        previous_code=previous_code,
        observation=observation,
    )
    response = await llm_client.chat(
        messages=messages,
        scene="figure_revision",
        temperature=0.2,
    )
    try:
        data = json.loads(response.content)
        if isinstance(data, dict) and data.get("status") == "need_redraw_plan":
            return "", {
                "raw_content": response.content,
                "warning": "need_redraw_plan",
                "usage": response.usage,
                "scene": "figure_revision",
                "model": _model_for_scene(llm_client, "figure_revision"),
                "redraw_reason": data.get("reason", ""),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    code, warning = extract_figure_code(response.content)
    return code, {
        "raw_content": response.content,
        "warning": warning,
        "usage": response.usage,
        "scene": "figure_revision",
        "model": _model_for_scene(llm_client, "figure_revision"),
    }


async def figure_semantic_inspection(
    llm_client: LLMClient,
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    render_result: dict,
    observation: dict,
) -> dict[str, Any]:
    """调用 Vision/LLM 对辅助线图做软语义观察。"""
    messages = build_figure_semantic_inspection_messages(
        question_text=question_text,
        diagram_description=diagram_description,
        solve_content=solve_content,
        figure_goal=figure_goal,
        render_result=render_result,
        observation=observation,
    )
    response = await llm_client.chat_json(
        messages=messages,
        scene="figure_semantic_inspection",
        temperature=0.1,
    )
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("keep", [])
    data.setdefault("missing", [])
    data.setdefault("wrong", [])
    data.setdefault("style_issues", [])
    data.setdefault("score", 0)
    data.setdefault("next_action", "accept_best_effort")
    data.setdefault("suggested_fix", "")
    data["usage"] = response.usage
    data["_llm"] = {
        "scene": "figure_semantic_inspection",
        "model": _model_for_scene(llm_client, "figure_semantic_inspection"),
    }
    return data


def extract_figure_code(content: str) -> tuple[str, str | None]:
    """从 LLM 输出中 best-effort 提取绘图代码。"""
    figure_match = _FIGURE_BLOCK_RE.search(content)
    if figure_match:
        return figure_match.group(1), None

    code_matches = _PYTHON_BLOCK_RE.findall(content)
    for code in code_matches:
        if _looks_like_python_figure_code(code):
            return code, "non_standard_python_block"

    if _looks_like_python_figure_code(content):
        return content.strip(), "raw_python_code"
    return "", "no_executable_figure_code"


def _looks_like_python_figure_code(content: str) -> bool:
    markers = ("plt.", "matplotlib", "ax.plot", "plt.plot", "fig, ax")
    return any(marker in content for marker in markers)
