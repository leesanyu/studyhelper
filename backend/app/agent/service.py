# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent 编排服务：Plan-and-Solve 实时流式调度。

stream_chat(request) → AsyncIterator[SSE_Event]:
  1. yield message_start（立即）
  2. yield thinking(planning) → 调用规划层
  3. 按规划执行工具：yield thinking(tool_exec) → 执行 → yield tool_result
  4. yield thinking(solving) → 调用执行层（实时流式 yield delta）
  5. yield answer_end（答案文本已完成，可解锁输入）
  6. 可选反思层（配置控制）：可在 figure 前或 figure 后运行
  7. 解析 python:figure / Figure Agent → render_figure → yield figure_result
  8. 持久化消息 → yield message_end
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, TypedDict

from app.agent.layers import (
    SolveResult,
    figure_draw_plan,
    figure_goal_check,
    figure_overlay_draw_plan,
    figure_overlay_revision_plan,
    figure_point_location,
    figure_revision_plan,
    figure_semantic_inspection,
    figure_target_crop,
    figure_trigger,
    plan,
    _FIGURE_BLOCK_RE,
)
from app.agent.auxiliary_extractor import extract_auxiliary_operations
from app.agent.figure_overlay import (
    OverlayRenderError,
    build_overlay_plan_from_auxiliary_text,
    crop_target_diagram,
    infer_layout_crop_box,
    inspect_overlay_semantics,
    render_overlay_plan,
    snap_localized_points_to_geometry,
)
from app.agent.geometry_normalizer import normalize_geometry_scene
from app.agent.geometry_renderer import build_geometry_figure_request
from app.agent.geometry_validator import validate_geometry_operations
from app.agent.tracing import create_agent_trace_recorder
from app.agent.llm_client import LLMClient, TextDelta
from app.agent.prompts import build_solving_messages
from app.agent.reflexion import reflexion_check
from app.agent.tools import KnowledgeResult, QuestionResult, extract_knowledge, process_question
from app.schemas.sandbox import PythonFigureRequest
from app.services.storage import LocalAssetStorage

logger = logging.getLogger(__name__)


# ── 仓储协议（对接 app.services）────────────────────────────────


class ChatMessageInfo(Protocol):
    """消息信息（ChatMessageRepository 返回的消息格式）。"""
    @property
    def role(self) -> str: ...
    @property
    def content(self) -> str: ...
    @property
    def message_id(self) -> str: ...


class MessageRepository(Protocol):
    """消息仓储协议。"""
    async def get_messages(
        self, session_id: str, limit: int = 20
    ) -> list[dict]: ...

    async def create_message(self, data: Any) -> Any: ...


class SessionRepository(Protocol):
    """会话仓储协议。"""
    async def update_context(
        self,
        session_id: str,
        *,
        current_question: str | None = None,
        current_diagram: str | None = None,
        current_knowledge: dict | None = None,
        current_geometry: dict | None = None,
    ) -> None: ...

    async def get_session(self, session_id: str) -> dict | None: ...


class AssetRepository(Protocol):
    """资产仓储协议。"""
    async def get_assets_by_ids(self, asset_ids: list[str]) -> list[dict]: ...


class SandboxService(Protocol):
    """图形渲染沙箱协议。"""
    async def render_figure(
        self, request: PythonFigureRequest
    ) -> dict: ...


class FigureAttempt(TypedDict, total=False):
    """一次绘图工具调用及其可回放上下文。"""

    source: str
    plan_type: str
    overlay_plan: dict[str, Any]
    code: str
    result: dict[str, Any] | None
    observation: dict[str, Any]


# ── SSE 事件构造 ──────────────────────────────────────────────────


def _sse_event(event: str, data: dict[str, Any] | None = None) -> dict:
    """构造 SSE 事件 dict。"""
    return {"event": event, "data": data or {}}


def _with_message_id(data: dict[str, Any], message_id: str | None) -> dict[str, Any]:
    """给后置事件补充消息归属；无持久化 ID 时保持兼容。"""
    if message_id:
        data["message_id"] = message_id
    return data


def _figure_result_data(result: dict[str, Any], message_id: str | None) -> dict[str, Any]:
    """构造 figure_result payload。"""
    return _with_message_id({
        "asset_id": result.get("asset_id", ""),
        "image_url": result.get("image_url", ""),
    }, message_id)


def _reflexion_result_data(
    payload: dict[str, Any],
    message_id: str | None,
) -> dict[str, Any]:
    """构造透明自检 payload。"""
    return _with_message_id({
        "status": str(payload.get("status") or "failed"),
        "visible_message": str(payload.get("visible_message") or ""),
        "corrected_content": str(payload.get("corrected_content") or ""),
        "issues": payload.get("issues") if isinstance(payload.get("issues"), list) else [],
        "figure_guidance": str(payload.get("figure_guidance") or ""),
    }, message_id)


def _figure_attempt_observation(
    *,
    source: str,
    ok: bool,
    error: str = "",
    score: int = 85,
    next_action: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 ReAct Observation；只描述工具事实，不替 LLM 判断几何策略。"""
    return {
        "tool": source,
        "execution": {"ok": ok, "error": error, "timeout": False},
        "image_quality": {"ok": ok, "non_blank": ok},
        "security_blocked": False,
        "score": score if ok else 0,
        "next_action": next_action or ("accept_best_effort" if ok else "revise_code"),
        "details": details or {},
    }


def _figure_attempt(
    *,
    source: str,
    code: str,
    result: dict[str, Any] | None,
    observation: dict[str, Any],
) -> FigureAttempt:
    """记录一次绘图尝试，供 ReAct Revision 和 best effort 选择。"""
    return {
        "source": source,
        "code": code,
        "result": result,
        "observation": observation,
    }


def _tool_warning_event(
    *,
    tool: str,
    message_id: str | None,
    status: str,
    code: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造非阻塞工具提示事件。"""
    data = {
        "status": status,
        "code": code,
        "message": message,
    }
    if extra:
        data.update(extra)
    return _sse_event("tool_result", {
        "tool": tool,
        "data": _with_message_id(data, message_id),
    })


# ── 工具结果格式化 ──────────────────────────────────────────────


def _format_tool_results(
    tool_results: dict[str, Any],
) -> tuple[dict[str, dict[str, int]], dict[str, str] | None]:
    """格式化工具执行结果。

    Returns:
        (tool_tokens, tool_result_texts)
    """
    if not tool_results:
        return {}, None

    texts: dict[str, str] = {}
    tokens: dict[str, dict[str, int]] = {}

    for tool_name, result in tool_results.items():
        if tool_name == "process_question" and isinstance(result, QuestionResult):
            texts[tool_name] = json.dumps({
                "subject": result.subject,
                "question_text": result.question_text,
                "has_figure": result.has_figure,
                "diagram_description": result.diagram_description,
                "question_count": result.question_count,
                "visual_observation": result.visual_observation,
                "geometry_scene_candidate": result.geometry_scene_candidate,
            }, ensure_ascii=False)
            if result.usage:
                tokens[tool_name] = result.usage
        elif tool_name == "extract_knowledge" and isinstance(result, KnowledgeResult):
            texts[tool_name] = json.dumps({
                "subject": result.subject,
                "knowledge_points": result.knowledge_points,
                "difficulty": result.difficulty,
                "grade_level": result.grade_level,
            }, ensure_ascii=False)
            if result.usage:
                tokens[tool_name] = result.usage

    return tokens, texts or None


# ── 工具结果摘要（供前端 tool_result 事件）──────────────────────────


def _tool_result_summary(tool_name: str, result: Any) -> dict[str, Any]:
    """生成工具结果摘要，供前端展示。"""
    if tool_name == "process_question" and isinstance(result, QuestionResult):
        return {
            "subject": result.subject,
            "question_text": result.question_text[:200],
            "has_figure": result.has_figure,
            "question_count": result.question_count,
            "has_geometry_scene": result.geometry_scene_candidate is not None,
            "geometry_warning_count": len(
                result.geometry_scene_candidate.get("warnings", [])
                if result.geometry_scene_candidate else []
            ),
        }
    if tool_name == "extract_knowledge" and isinstance(result, KnowledgeResult):
        return {
            "subject": result.subject,
            "knowledge_points": result.knowledge_points,
            "difficulty": result.difficulty,
            "grade_level": result.grade_level,
        }
    return {}


def _current_geometry(
    tool_results: dict[str, Any],
    session_context: dict[str, Any],
) -> dict[str, Any] | None:
    q_result = tool_results.get("process_question")
    if isinstance(q_result, QuestionResult) and q_result.geometry_scene_candidate:
        return q_result.geometry_scene_candidate
    current = session_context.get("current_geometry")
    return current if isinstance(current, dict) else None


def _current_question_text(
    tool_results: dict[str, Any],
    session_context: dict[str, Any],
) -> str:
    q_result = tool_results.get("process_question")
    if isinstance(q_result, QuestionResult):
        return q_result.question_text
    return str(session_context.get("current_question") or "")


def _current_diagram_description(
    tool_results: dict[str, Any],
    session_context: dict[str, Any],
) -> str:
    q_result = tool_results.get("process_question")
    if isinstance(q_result, QuestionResult):
        return q_result.diagram_description
    return str(session_context.get("current_diagram") or "")


def _current_visual_observation(tool_results: dict[str, Any]) -> dict | None:
    q_result = tool_results.get("process_question")
    if isinstance(q_result, QuestionResult):
        return q_result.visual_observation
    return None


def _looks_like_geometry_solution(content: str) -> bool:
    geometry_markers = (
        "辅助线",
        "连接",
        "作",
        "垂直",
        "⊥",
        "平行",
        "共线",
        "交于",
        "点",
        "线段",
        "三角形",
        "全等",
    )
    return any(marker in content for marker in geometry_markers)


def _should_run_figure_agent(
    trigger: dict[str, Any],
    solve_content: str,
    *,
    has_assets: bool,
) -> bool:
    if bool(trigger.get("figure_needed")):
        return True
    if trigger.get("existing_python_figure"):
        return True
    return has_assets and _looks_like_geometry_solution(solve_content)


def _figure_content_with_reflexion(
    content: str,
    reflexion_payload: dict[str, Any] | None,
) -> str:
    """将透明自检结果并入 Figure Agent 文本上下文。"""
    if not reflexion_payload:
        return content
    corrected = str(reflexion_payload.get("corrected_content") or "").strip()
    base_content = corrected or content
    status = str(reflexion_payload.get("status") or "")
    visible_message = str(reflexion_payload.get("visible_message") or "")
    figure_guidance = str(reflexion_payload.get("figure_guidance") or "")
    return (
        f"{base_content}\n\n"
        "【透明自检】\n"
        f"状态：{status}\n"
        f"结果：{visible_message}\n"
        f"绘图提示：{figure_guidance}"
    )


def _effective_tool_calls(
    tool_calls: list[str],
    *,
    has_uploaded_image: bool,
) -> list[str]:
    """对规划层工具列表做确定性兜底。

    上传图片代表本轮是新题图输入，即使规划层受旧会话上下文影响误判为追问，
    编排层也必须先执行题目识别和知识点提取。
    """
    normalized = [tool for tool in tool_calls if tool in {"process_question", "extract_knowledge"}]
    if not has_uploaded_image:
        return normalized

    result: list[str] = ["process_question", "extract_knowledge"]
    for tool in normalized:
        if tool not in result:
            result.append(tool)
    return result


async def _rollback_repository(repository: Any) -> None:
    rollback = getattr(repository, "rollback", None)
    if rollback is None:
        return
    try:
        result = rollback()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        logger.warning("回滚仓储事务失败", exc_info=True)


# ── 图片摘要生成 ─────────────────────────────────────────────────


async def _build_image_summary(
    asset_ids: list[str],
    asset_repository: AssetRepository | None,
    settings: Any,
) -> tuple[str | None, str | None, str | None]:
    """从 asset_ids 提取图片摘要和 base64 数据。

    Returns:
        (image_summary, image_base64, image_text) 或 (None, None, None)。
    """
    if not asset_ids or asset_repository is None:
        return None, None, None

    try:
        assets = await asset_repository.get_assets_by_ids(asset_ids)
    except Exception:
        logger.warning("加载资产失败", exc_info=True)
        return None, None, None

    if not assets:
        return None, None, None

    # 取第一个图片资产
    image_asset = None
    for asset in assets:
        mime = asset.get("mime_type", "")
        if mime and mime.startswith("image/"):
            image_asset = asset
            break

    if image_asset is None:
        return None, None, None

    # 构建摘要
    size_kb = (image_asset.get("size_bytes", 0) or 0) // 1024
    summary = f"[用户上传了一张包含数学题目的图片，{size_kb}KB]"

    # 尝试读取图片 base64
    image_base64 = None
    object_key = image_asset.get("object_key")
    if object_key and settings:
        import os
        storage_path = os.path.join(
            getattr(settings, "asset_storage_path", "/tmp/studyhelper-assets"),
            object_key,
        )
        try:
            if os.path.isfile(storage_path):
                with open(storage_path, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode("ascii")
        except Exception:
            logger.warning("读取图片文件失败: %s", storage_path, exc_info=True)

    return summary, image_base64, None


async def _load_first_image_asset(
    asset_ids: list[str],
    asset_repository: AssetRepository | None,
    settings: Any,
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    """读取第一个图片资产，返回资产、文件路径和 base64。"""
    if not asset_ids or asset_repository is None or settings is None:
        return None, None, None
    try:
        assets = await asset_repository.get_assets_by_ids(asset_ids)
    except Exception:
        logger.warning("加载 overlay 资产失败", exc_info=True)
        return None, None, None
    image_asset = None
    for asset in assets:
        mime = str(asset.get("mime_type") or "")
        if mime.startswith("image/"):
            image_asset = asset
            break
    if image_asset is None:
        return None, None, None
    object_key = image_asset.get("object_key")
    if not object_key:
        return image_asset, None, None
    image_path = Path(getattr(settings, "asset_storage_path", "/tmp/studyhelper-assets")) / str(object_key)
    if not image_path.exists():
        return image_asset, None, None
    try:
        image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError:
        logger.warning("读取 overlay 图片失败: %s", image_path, exc_info=True)
        return image_asset, image_path, None
    return image_asset, image_path, image_base64


def _extract_auxiliary_text(content: str) -> str:
    """尽量保留 Solve 原文中的辅助线句。"""
    match = re.search(r"【辅助线】\s*([^\n。]+[。.]?)", content)
    if match:
        return match.group(1).strip()
    for line in content.splitlines():
        stripped = line.strip()
        if "辅助线" in stripped or stripped.startswith(("延长", "连接", "过点", "作")):
            return stripped
    return ""


def _overlay_point_labels(*values: Any) -> list[str]:
    """从题干、解答和 Goal 中提取候选点标签。"""
    labels: set[str] = set()
    for value in values:
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
        for label in re.findall(r"\b[A-Z]\b", text):
            labels.add(label)
        for segment in re.findall(r"\b[A-Z]{2}\b", text):
            labels.update(segment)
    return sorted(labels)


def _wants_overlay(goal: dict[str, Any]) -> bool:
    layout_hint = goal.get("layout_hint")
    layout_type = layout_hint.get("type") if isinstance(layout_hint, dict) else ""
    return goal.get("render_mode") == "overlay_on_crop" or layout_type == "overlay_on_crop"


def _build_local_figure_trigger_payload(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    auxiliary_text: str,
    existing_python_figure: str | None,
    has_assets: bool,
    reason: str,
    warning: str,
) -> dict[str, Any]:
    """不调用 LLM 时的轻量触发判断，尽量让 Figure Agent 继续尝试。"""
    auxiliary_intent = auxiliary_text.strip()
    figure_needed = bool(
        auxiliary_intent
        or existing_python_figure
        or (has_assets and _looks_like_geometry_solution(solve_content))
        or _looks_like_geometry_solution(question_text)
        or _looks_like_geometry_solution(diagram_description)
    )
    trigger_source = "auxiliary_text" if auxiliary_intent else "local_geometry_fallback"
    warnings = [warning]
    if figure_needed and not auxiliary_intent and has_assets:
        warnings.append("figure_needed_inferred_by_local_geometry")
    return {
        "figure_needed": figure_needed,
        "reason": reason,
        "auxiliary_intent": auxiliary_intent,
        "confidence": 1.0 if auxiliary_intent else (0.55 if figure_needed else 0.0),
        "existing_python_figure": existing_python_figure or "",
        "trigger_source": trigger_source,
        "warnings": warnings,
    }


def _infer_target_diagram_label(*values: Any) -> str:
    text_parts = [
        json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
        for value in values
    ]
    text = "\n".join(text_parts)
    explicit = re.search(r"图\s*([0-9一二三四五六七八九])", text)
    if explicit:
        return f"图{_normalize_index_text(explicit.group(1))}"
    question_index = re.search(r"第\s*[（(]?\s*([0-9一二三四五六七八九])\s*[）)]?\s*问", text)
    if question_index:
        return f"图{_normalize_index_text(question_index.group(1))}"
    return ""


def _normalize_index_text(value: str) -> str:
    mapping = {
        "一": "1",
        "二": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
    }
    return mapping.get(value, value)


def _expected_auxiliary_from_text(auxiliary_text: str) -> list[Any]:
    if not auxiliary_text:
        return []
    expected: list[Any] = [auxiliary_text]
    parsed = extract_auxiliary_operations(f"【辅助线】{auxiliary_text}")
    for operation in parsed.get("operations", []):
        if isinstance(operation, dict):
            expected.append({
                "type": operation.get("type"),
                "params": operation.get("params", {}),
            })
    return expected


def _build_local_figure_goal_payload(
    *,
    question_text: str,
    diagram_description: str,
    visual_observation: dict | None,
    geometry_scene_candidate: dict | None,
    solve_content: str,
    auxiliary_text: str,
    trigger: dict[str, Any],
    has_assets: bool,
    reason: str,
) -> dict[str, Any]:
    auxiliary_intent = auxiliary_text or str(trigger.get("auxiliary_intent") or "")
    target_diagram = _infer_target_diagram_label(
        question_text,
        diagram_description,
        solve_content,
        visual_observation,
        geometry_scene_candidate,
        trigger,
    )
    render_mode = "overlay_on_crop" if has_assets else "schematic"
    warnings = ["figure_goal_llm_skipped"]
    if not auxiliary_intent:
        warnings.append("auxiliary_intent_missing")
    layout_hint: dict[str, Any] = {
        "type": render_mode,
        "source": "local_goal_fallback",
    }
    if target_diagram:
        layout_hint["target_diagram"] = target_diagram
    return {
        "goal_status": "ready" if auxiliary_intent or has_assets else "needs_inference",
        "render_mode": render_mode,
        "target_diagram": target_diagram,
        "coordinate_space": "crop_pixels" if has_assets else "schematic",
        "normalized_auxiliary_intent": auxiliary_intent,
        "expected_auxiliary": _expected_auxiliary_from_text(auxiliary_intent),
        "original_figure_elements": _overlay_point_labels(
            question_text,
            diagram_description,
            visual_observation,
            geometry_scene_candidate,
        ),
        "layout_hint": layout_hint,
        "style_requirements": {"auxiliary_lines": "red dashed"},
        "warnings": warnings,
        "_local": {
            "reason": reason,
            "source": "figure_goal_llm_disabled",
        },
    }


def _llm_model_name(llm_client: Any, scene: str) -> str:
    getter = getattr(llm_client, "model_for_scene", None)
    if callable(getter):
        try:
            return str(getter(scene))
        except Exception:
            return ""
    return ""


# ── AgentService ──────────────────────────────────────────────────


class AgentService:
    """Agent 编排服务：Plan-and-Solve 实时流式调度。

    连接 LLMClient + 分层逻辑 + 仓储 + 沙箱，提供流式聊天接口。
    每个步骤的结果实时通过 SSE 事件推送给前端。
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        asset_repository: AssetRepository | None = None,
        session_repository: SessionRepository | None = None,
        message_repository: MessageRepository | None = None,
        sandbox_service: SandboxService | None = None,
        settings: Any | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._asset_repo = asset_repository
        self._session_repo = session_repository
        self._message_repo = message_repository
        self._sandbox_service = sandbox_service
        self._settings = settings

    def _semantic_inspection_enabled(self) -> bool:
        return bool(getattr(self._settings, "figure_semantic_inspection_enabled", False))

    def _pre_figure_reflexion_enabled(self) -> bool:
        return bool(getattr(self._settings, "pre_figure_reflexion_enabled", False))

    def _figure_trigger_llm_enabled(self) -> bool:
        return bool(getattr(self._settings, "figure_trigger_llm_enabled", True))

    def _figure_goal_check_llm_enabled(self) -> bool:
        return bool(getattr(self._settings, "figure_goal_check_llm_enabled", True))

    def _figure_target_crop_vision_enabled(self) -> bool:
        return bool(getattr(self._settings, "figure_target_crop_vision_enabled", False))

    def _figure_overlay_revision_enabled(self) -> bool:
        return bool(getattr(self._settings, "figure_overlay_revision_enabled", True))

    def _figure_code_revision_enabled(self) -> bool:
        return bool(getattr(self._settings, "figure_code_revision_enabled", True))

    async def _run_transparent_reflexion_stage(
        self,
        *,
        content: str,
        strategy: str,
        difficulty: str,
        need_deep_reflexion: bool,
        trace: Any | None = None,
    ) -> tuple[dict[str, Any], str, dict[str, int] | None]:
        """运行用户可见的透明自检，返回事件 payload、Figure 文本和 usage。"""
        try:
            result = await reflexion_check(
                self._llm_client,
                content=content,
                strategy=strategy,
                difficulty=difficulty,
                need_deep_reflexion=need_deep_reflexion,
            )
        except Exception:
            logger.warning("[Reflexion] 透明自检异常，继续后续流程", exc_info=True)
            payload = {
                "status": "failed",
                "visible_message": "自检未完成：AI 自检服务暂时不可用。当前解答未经过自检。",
                "corrected_content": "",
                "issues": ["reflexion_error"],
                "figure_guidance": "自检失败，Figure Agent 只能基于原答案和题图上下文 best effort 绘图。",
            }
            if trace is not None:
                trace.record("reflexion_error", {"stage": "pre_figure"})
                trace.record("reflexion_result", payload)
            return payload, _figure_content_with_reflexion(content, payload), None

        corrected_content = result.content.strip() if result.had_violation else ""
        if result.had_violation and not corrected_content:
            payload = {
                "status": "unreliable",
                "visible_message": "自检未通过：发现原答案可能存在问题，但未生成可靠修正版。",
                "corrected_content": "",
                "issues": ["reflexion_unreliable"],
                "figure_guidance": "原答案存在自检风险，Figure Agent 需要保留风险提示并谨慎 best effort 绘图。",
            }
        elif result.had_violation:
            payload = {
                "status": "corrected",
                "visible_message": "自检修正：发现原答案可能存在问题，已生成修正版。",
                "corrected_content": corrected_content,
                "issues": ["answer_corrected"],
                "figure_guidance": "优先使用 corrected_content 中的修正版整理绘图目标。",
            }
        else:
            payload = {
                "status": "passed",
                "visible_message": "自检通过：未发现明显计算或逻辑问题。",
                "corrected_content": "",
                "issues": [],
                "figure_guidance": "可以基于原答案整理绘图目标。",
            }
        if trace is not None:
            trace.record("reflexion_result", {
                **payload,
                "usage": result.usage,
            })
        return payload, _figure_content_with_reflexion(content, payload), result.usage

    async def stream_chat(
        self,
        *,
        session_id: str | None = None,
        message: str,
        asset_ids: list[str] | None = None,
        client_user_id: str = "anonymous",
    ) -> AsyncIterator[dict[str, Any]]:
        """Plan-and-Solve 编排主循环，实时流式输出 SSE 事件。

        Args:
            session_id: 会话 ID（None 则创建新会话）
            message: 用户消息文本
            asset_ids: 上传的图片资产 ID 列表
            client_user_id: 客户端用户标识
        """
        asset_ids = asset_ids or []
        trace = create_agent_trace_recorder(
            settings=self._settings,
            session_id=session_id,
            client_user_id=client_user_id,
            message=message,
            asset_ids=asset_ids,
        )
        trace_status = "ok"

        try:
            # 立即发送 message_start，让前端知道连接已建立
            yield _sse_event("message_start", {"session_id": session_id or "local-session"})

            # 1. 加载对话历史
            chat_history = await self._load_chat_history(session_id)

            # 2. 加载当前题目上下文（从会话表）
            session_context = await self._load_session_context(session_id)

            # 3. 构建图片摘要
            image_summary, image_base64, _ = await _build_image_summary(
                asset_ids, self._asset_repo, self._settings
            )
            logger.info("[Agent] session=%s msg=%.40r has_image=%s", session_id, message, image_base64 is not None)
            if trace is not None:
                trace.record("image_summary", {
                    "image_summary": image_summary,
                    "has_image": image_base64 is not None,
                    "asset_ids": asset_ids,
                })

            # 4. 调用规划层
            yield _sse_event("thinking", {"type": "planning", "message": "分析题目中..."})
            try:
                plan_result = await plan(
                    self._llm_client,
                    user_message=message,
                    image_summary=image_summary,
                    chat_history=chat_history,
                    current_question=session_context.get("current_question"),
                    current_knowledge=session_context.get("current_knowledge"),
                    current_diagram=session_context.get("current_diagram"),
                )
            except Exception:
                trace_status = "error"
                if trace is not None:
                    trace.record("error", {"stage": "planning", "message": "AI 服务暂时不可用"})
                yield _sse_event("error", {"code": "ai_unavailable", "message": "AI 服务暂时不可用"})
                return
            if trace is not None:
                trace.record("planning_result", {
                    "question_type": plan_result.question_type,
                    "strategy": plan_result.strategy,
                    "tool_calls": plan_result.tool_calls,
                    "need_deep_reflexion": plan_result.need_deep_reflexion,
                    "usage": plan_result.usage,
                })

            logger.info("[Plan] question_type=%s strategy=%s tools=%s deep_reflexion=%s",
                        plan_result.question_type, plan_result.strategy,
                        plan_result.tool_calls, plan_result.need_deep_reflexion)

            # 5. 执行工具（按 plan_result.tool_calls 顺序）
            tool_results: dict[str, Any] = {}
            tool_tokens: dict[str, dict[str, int]] = {}
            difficulty = "中等"
            tool_calls = _effective_tool_calls(
                plan_result.tool_calls,
                has_uploaded_image=image_summary is not None,
            )
            for tool_name in tool_calls:
                try:
                    if tool_name == "process_question":
                        yield _sse_event("thinking", {"type": "tool_exec", "message": "识别题目中..."})
                        logger.info("[Tool] process_question start has_image=%s", image_base64 is not None)
                        result = await process_question(
                            self._llm_client,
                            image_base64=image_base64,
                            text=message,
                        )
                        scene = normalize_geometry_scene(
                            question_text=result.question_text,
                            diagram_description=result.diagram_description,
                            has_figure=result.has_figure,
                            visual_observation=result.visual_observation,
                        )
                        result = replace(result, geometry_scene_candidate=scene)
                        tool_results["process_question"] = result
                        if result.usage:
                            tool_tokens["process_question"] = result.usage
                        logger.info("[Tool] process_question done subject=%s has_figure=%s", result.subject, result.has_figure)
                        if trace is not None:
                            tool_scene = "vision" if image_base64 else "question_parse"
                            trace.record("process_question_result", {
                                "scene": tool_scene,
                                "model": _llm_model_name(self._llm_client, tool_scene),
                                "subject": result.subject,
                                "question_text": result.question_text,
                                "has_figure": result.has_figure,
                                "diagram_description": result.diagram_description,
                                "question_count": result.question_count,
                                "visual_observation": result.visual_observation,
                                "geometry_scene_candidate": result.geometry_scene_candidate,
                                "usage": result.usage,
                            })
                        # 换题时：新上下文写入后，旧上下文自然被覆盖
                        await self._update_session_question(session_id, result)
                        yield _sse_event("tool_result", {
                            "tool": "process_question",
                            "data": _tool_result_summary("process_question", result),
                        })
                    elif tool_name == "extract_knowledge":
                        yield _sse_event("thinking", {"type": "tool_exec", "message": "提取知识点中..."})
                        logger.info("[Tool] extract_knowledge start")
                        q_result = tool_results.get("process_question")
                        if isinstance(q_result, QuestionResult):
                            result = await extract_knowledge(
                                self._llm_client,
                                question_text=q_result.question_text,
                                subject=q_result.subject,
                            )
                            tool_results["extract_knowledge"] = result
                            if result.usage:
                                tool_tokens["extract_knowledge"] = result.usage
                            difficulty = result.difficulty
                            logger.info("[Tool] extract_knowledge done difficulty=%s points=%s",
                                        result.difficulty, result.knowledge_points)
                            if trace is not None:
                                trace.record("extract_knowledge_result", {
                                    "scene": "knowledge",
                                    "model": _llm_model_name(self._llm_client, "knowledge"),
                                    "subject": result.subject,
                                    "knowledge_points": result.knowledge_points,
                                    "difficulty": result.difficulty,
                                    "grade_level": result.grade_level,
                                    "usage": result.usage,
                                })
                            await self._update_session_knowledge(session_id, result)
                            yield _sse_event("tool_result", {
                                "tool": "extract_knowledge",
                                "data": _tool_result_summary("extract_knowledge", result),
                            })
                except Exception:
                    trace_status = "error"
                    if trace is not None:
                        trace.record("error", {"stage": "tool", "tool": tool_name})
                    yield _sse_event("error", {"code": "tool_error", "message": f"工具 {tool_name} 执行失败"})
                    return

            # 6. 调用执行层（实时流式输出 delta）
            yield _sse_event("thinking", {"type": "solving", "message": "生成回复中..."})
            logger.info("[Solve] start strategy=%s", plan_result.strategy)

            # 直接迭代 LLM 流式输出，实时 yield delta 事件
            # 同时收集完整内容供 figure 解析和反思使用
            solve_messages = build_solving_messages(
                strategy=plan_result.strategy,
                user_message=message,
                image_summary=image_summary,
                chat_history=chat_history,
                current_question=session_context.get("current_question"),
                current_knowledge=session_context.get("current_knowledge"),
                current_diagram=session_context.get("current_diagram"),
                current_geometry=_current_geometry(tool_results, session_context),
                tool_results=_format_tool_results(tool_results)[1],
            )
            if trace is not None:
                trace.record("solve_prompt", {
                    "scene": "solving",
                    "model": _llm_model_name(self._llm_client, "solving"),
                    "strategy": plan_result.strategy,
                    "messages": solve_messages,
                })

            content_chunks: list[str] = []
            solve_usage: dict[str, int] = {}
            try:
                async for event in self._llm_client.stream_chat(messages=solve_messages, scene="solving"):
                    if isinstance(event, TextDelta):
                        content_chunks.append(event.text)
                        yield _sse_event("delta", {"text": event.text, "session_id": session_id or ""})
                    elif hasattr(event, "usage") and event.usage:
                        solve_usage = event.usage
            except Exception:
                trace_status = "error"
                if trace is not None:
                    trace.record("error", {"stage": "solving", "message": "AI 服务暂时不可用"})
                yield _sse_event("error", {"code": "ai_unavailable", "message": "AI 服务暂时不可用"})
                return

            full_content = "".join(content_chunks)
            figure_blocks = _FIGURE_BLOCK_RE.findall(full_content)
            logger.info("[Solve] done content_len=%d figures=%d", len(full_content), len(figure_blocks))
            if trace is not None:
                trace.record("solve_result", {
                    "scene": "solving",
                    "model": _llm_model_name(self._llm_client, "solving"),
                    "content": full_content,
                    "figure_blocks": figure_blocks,
                    "usage": solve_usage,
                })
            yield _sse_event("answer_end", {"session_id": session_id or "local-session"})

            solve_content_for_figure = full_content
            reflexion_payload: dict[str, Any] | None = None
            reflexion_usage: dict[str, int] | None = None

            if self._pre_figure_reflexion_enabled():
                reflexion_payload, solve_content_for_figure, reflexion_usage = (
                    await self._run_transparent_reflexion_stage(
                        content=full_content,
                        strategy=plan_result.strategy,
                        difficulty=difficulty,
                        need_deep_reflexion=plan_result.need_deep_reflexion,
                        trace=trace,
                    )
                )

            # 7. 文字答案完成后先持久化 assistant 消息，后续事件才能挂回原气泡。
            message_id = await self._persist_messages(
                session_id=session_id,
                user_message=message,
                assistant_content=full_content,
                plan_result=plan_result,
                solve_usage=solve_usage,
                tool_tokens=tool_tokens,
                reflexion_usage=reflexion_usage,
                difficulty=difficulty,
            )
            if trace is not None:
                trace.record("message_persisted", {"message_id": message_id})

            if reflexion_payload is not None:
                yield _sse_event(
                    "reflexion_result",
                    _reflexion_result_data(reflexion_payload, message_id),
                )

            # 8. 后置绘图。结构化几何只是 Figure Agent 的一个候选 Action，不再终结流程。
            geometry_scene = _current_geometry(tool_results, session_context)
            structured_attempt: FigureAttempt | None = None
            if geometry_scene:
                structured_attempt = await self._render_structured_geometry(
                    session_id=session_id,
                    message_id=message_id,
                    full_content=solve_content_for_figure,
                    geometry_scene=geometry_scene,
                    trace=trace,
                )
                if trace is not None:
                    trace.record("structured_geometry_attempt", {
                        "has_geometry_scene": True,
                        "has_candidate": structured_attempt is not None,
                        "candidate_source": structured_attempt.get("source") if structured_attempt else "",
                    })
                if structured_attempt is not None and structured_attempt.get("result") is None:
                    observation = structured_attempt.get("observation") or {}
                    details = observation.get("details", {}) if isinstance(observation, dict) else {}
                    validation = details.get("validation", {}) if isinstance(details, dict) else {}
                    yield _tool_warning_event(
                        tool="geometry_validator",
                        message_id=message_id,
                        status="failed",
                        code=validation.get("code") or "geometry_check_failed",
                        message=observation.get("execution", {}).get("error")
                        or validation.get("message")
                        or "辅助线校验失败，转入 Figure Agent",
                        extra={
                            "rejected_operations": validation.get("rejected_operations", []),
                        },
                    )

            async for event in self._run_figure_agent(
                session_id=session_id,
                message_id=message_id,
                asset_ids=asset_ids,
                question_text=_current_question_text(tool_results, session_context),
                diagram_description=_current_diagram_description(tool_results, session_context),
                visual_observation=_current_visual_observation(tool_results),
                geometry_scene_candidate=geometry_scene,
                solve_content=solve_content_for_figure,
                reflexion_result=reflexion_payload,
                existing_python_figure=figure_blocks[0] if figure_blocks else "",
                initial_attempt=structured_attempt,
                trace=trace,
            ):
                yield event

            yield _sse_event("message_end", {
                "session_id": session_id or "local-session",
                "message_id": message_id or "",
            })
        finally:
            if trace is not None:
                trace.close(status=trace_status, data={"session_id": session_id})

    # ── 内部辅助方法 ─────────────────────────────────────────────

    async def _load_chat_history(
        self, session_id: str | None
    ) -> list[dict] | None:
        """加载最近 20 条对话历史。"""
        if not session_id or not self._message_repo:
            return None
        try:
            raw_messages = await self._message_repo.get_messages(
                session_id, limit=20
            )
            return [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in raw_messages
            ]
        except Exception:
            await _rollback_repository(self._message_repo)
            return None

    async def _load_session_context(
        self, session_id: str | None
    ) -> dict[str, Any]:
        """从会话表加载当前题目上下文。"""
        if not session_id or not self._session_repo:
            return {}
        try:
            session = await self._session_repo.get_session(session_id)
            if not session:
                return {}
            return {
                "current_question": session.get("current_question"),
                "current_knowledge": session.get("current_knowledge"),
                "current_diagram": session.get("current_diagram"),
                "current_geometry": session.get("current_geometry"),
            }
        except Exception:
            await _rollback_repository(self._session_repo)
            return {}

    async def _update_session_question(
        self, session_id: str | None, result: QuestionResult
    ) -> None:
        """更新会话题目上下文（process_question 后）。"""
        if not session_id or not self._session_repo:
            return
        try:
            await self._session_repo.update_context(
                session_id,
                current_question=result.question_text,
                current_diagram=result.diagram_description or "",
                current_knowledge={"subject": result.subject} if result.subject else None,
                current_geometry=result.geometry_scene_candidate,
            )
        except Exception:
            await _rollback_repository(self._session_repo)
            pass

    async def _update_session_knowledge(
        self, session_id: str | None, result: KnowledgeResult
    ) -> None:
        """更新会话知识点上下文（extract_knowledge 后）。"""
        if not session_id or not self._session_repo:
            return
        try:
            await self._session_repo.update_context(
                session_id,
                current_knowledge={
                    "subject": result.subject,
                    "knowledge_points": result.knowledge_points,
                    "difficulty": result.difficulty,
                    "grade_level": result.grade_level,
                },
            )
        except Exception:
            await _rollback_repository(self._session_repo)
            pass

    async def _render_structured_geometry(
        self,
        *,
        session_id: str | None,
        message_id: str | None,
        full_content: str,
        geometry_scene: dict[str, Any],
        trace: Any | None = None,
    ) -> FigureAttempt | None:
        extracted = extract_auxiliary_operations(full_content)
        operations = extracted.get("operations", [])
        if trace is not None:
            trace.record("structured_geometry_extracted", {
                "operations": operations,
                "warnings": extracted.get("warnings", []),
            })
        if not operations:
            return None
        check = validate_geometry_operations(geometry_scene, operations)
        if trace is not None:
            trace.record("structured_geometry_validation", check)
        if not check.get("ok"):
            return _figure_attempt(
                source="structured_renderer",
                code="",
                result=None,
                observation=_figure_attempt_observation(
                    source="structured_renderer",
                    ok=False,
                    error=check.get("message") or "辅助线校验失败",
                    details={
                        "phase": "validation",
                        "operations": operations,
                        "validation": check,
                        "message_id": message_id,
                    },
                ),
            )
        if not self._sandbox_service:
            if trace is not None:
                trace.record("structured_geometry_skipped", {"reason": "sandbox_service_missing"})
            return _figure_attempt(
                source="structured_renderer",
                code="",
                result=None,
                observation=_figure_attempt_observation(
                    source="structured_renderer",
                    ok=False,
                    error="sandbox_service_missing",
                    details={"phase": "render", "operations": operations, "validation": check},
                ),
            )
        try:
            request = build_geometry_figure_request(
                geometry_scene,
                check.get("accepted_operations", []),
                session_id=session_id,
                message_id=message_id,
            )
            if trace is not None:
                trace.record("structured_geometry_render_request", {"request": request})
            fig_result = await self._sandbox_service.render_figure(request)
            if trace is not None:
                trace.record("structured_geometry_render_result", {"response": fig_result})
            observation = _figure_attempt_observation(
                source="structured_renderer",
                ok=True,
                details={
                    "phase": "render",
                    "operations": operations,
                    "validation": check,
                    "warnings": check.get("warnings", []),
                    "needs_visual_review": bool(check.get("needs_visual_review")),
                },
            )
            if check.get("needs_visual_review"):
                observation["next_action"] = "revise_code"
                observation["score"] = 65
            return _figure_attempt(
                source="structured_renderer",
                code=request.code,
                result=fig_result,
                observation=observation,
            )
        except Exception:
            logger.warning("结构化几何渲染失败", exc_info=True)
            if trace is not None:
                trace.record("structured_geometry_render_error", {"message": "辅助线图无法生成可靠示意位置"})
            return _figure_attempt(
                source="structured_renderer",
                code="",
                result=None,
                observation=_figure_attempt_observation(
                    source="structured_renderer",
                    ok=False,
                    error="辅助线图无法生成可靠示意位置",
                    details={
                        "phase": "render",
                        "operations": operations,
                        "validation": check,
                    },
                ),
            )

    async def _run_figure_agent(
        self,
        *,
        session_id: str | None,
        message_id: str | None,
        asset_ids: list[str],
        question_text: str,
        diagram_description: str,
        visual_observation: dict | None,
        geometry_scene_candidate: dict | None,
        solve_content: str,
        reflexion_result: dict[str, Any] | None,
        existing_python_figure: str | None,
        initial_attempt: FigureAttempt | None = None,
        trace: Any | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self._sandbox_service and initial_attempt is None and not asset_ids:
            if trace is not None:
                trace.record("figure_agent_skipped", {"reason": "sandbox_service_missing"})
            return

        auxiliary_text = _extract_auxiliary_text(solve_content)
        trigger = await self._build_figure_trigger(
            question_text=question_text,
            diagram_description=diagram_description,
            solve_content=solve_content,
            auxiliary_text=auxiliary_text,
            existing_python_figure=existing_python_figure,
            has_assets=bool(asset_ids),
        )
        if trace is not None:
            trace.record("figure_context", {
                "question_text": question_text,
                "diagram_description": diagram_description,
                "solve_content": solve_content,
                "reflexion_result": reflexion_result,
            })
            trace.record("figure_trigger", trigger)

        if not _should_run_figure_agent(trigger, solve_content, has_assets=bool(asset_ids)):
            if trace is not None:
                trace.record("figure_agent_skipped", {
                    "reason": "trigger_not_needed",
                    "trigger": trigger,
            })
            return

        attempt_count = 1 if initial_attempt is not None else 0

        async def build_goal(reason: str) -> dict[str, Any]:
            if (
                auxiliary_text
                and asset_ids
                and self._asset_repo is not None
                and build_overlay_plan_from_auxiliary_text(auxiliary_text) is not None
            ):
                goal_result = _build_local_figure_goal_payload(
                    question_text=question_text,
                    diagram_description=diagram_description,
                    visual_observation=visual_observation,
                    geometry_scene_candidate=geometry_scene_candidate,
                    solve_content=solve_content,
                    auxiliary_text=auxiliary_text,
                    trigger={**trigger, "redraw_reason": reason},
                    has_assets=bool(asset_ids),
                    reason=f"{reason}:auxiliary_text_fast_path",
                )
                if trace is not None:
                    trace.record("figure_goal", {"reason": reason, **goal_result})
                return goal_result

            if not self._figure_goal_check_llm_enabled():
                goal_result = _build_local_figure_goal_payload(
                    question_text=question_text,
                    diagram_description=diagram_description,
                    visual_observation=visual_observation,
                    geometry_scene_candidate=geometry_scene_candidate,
                    solve_content=solve_content,
                    auxiliary_text=auxiliary_text,
                    trigger={**trigger, "redraw_reason": reason},
                    has_assets=bool(asset_ids),
                    reason=reason,
                )
                if trace is not None:
                    trace.record("figure_goal", {"reason": reason, **goal_result})
                return goal_result

            goal_result = await figure_goal_check(
                self._llm_client,
                question_text=question_text,
                diagram_description=diagram_description,
                visual_observation=visual_observation,
                geometry_scene_candidate=geometry_scene_candidate,
                solve_content=solve_content,
                auxiliary_intent=str(trigger.get("auxiliary_intent") or ""),
                trigger={**trigger, "redraw_reason": reason},
            )
            if trace is not None:
                trace.record("figure_goal", {"reason": reason, **goal_result})
            return goal_result

        async def draw_code(goal_result: dict[str, Any], reason: str) -> str:
            drawn_code, draw_metadata = await figure_draw_plan(
                self._llm_client,
                question_text=question_text,
                diagram_description=diagram_description,
                solve_content=solve_content,
                figure_goal=goal_result,
            )
            if trace is not None:
                trace.record("figure_draw_plan", {"reason": reason, **draw_metadata})
                trace.record("figure_draw_code", {"reason": reason, "code": drawn_code})
            return drawn_code

        best_result = (
            initial_attempt.get("result")
            if initial_attempt is not None and initial_attempt.get("result") is not None
            else None
        )

        async def render_code(
            code_to_render: str,
            *,
            source: str = "draw_plan_llm",
        ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
            nonlocal attempt_count
            if not self._sandbox_service:
                observation = _figure_attempt_observation(
                    source=source,
                    ok=False,
                    error="sandbox_service_missing",
                )
                if trace is not None:
                    trace.record("figure_observation", observation)
                return None, observation
            attempt_count += 1
            request = PythonFigureRequest(
                code=code_to_render,
                session_id=session_id,
                message_id=message_id,
            )
            try:
                result = await self._sandbox_service.render_figure(request)
            except Exception as exc:
                logger.warning("Figure Agent 渲染失败", exc_info=True)
                observation = _figure_attempt_observation(
                    source=source,
                    ok=False,
                    error=str(exc),
                )
                if trace is not None:
                    trace.record("figure_execution", {"request": request, "error": str(exc)})
                    trace.record("figure_observation", observation)
                return None, observation

            observation = _figure_attempt_observation(source=source, ok=True)
            if trace is not None:
                trace.record("figure_execution", {"request": request, "response": result})
                trace.record("figure_observation", observation)
            return result, observation

        async def inspect_semantics(
            goal_result: dict[str, Any],
            render_result: dict[str, Any],
            observation: dict[str, Any],
        ) -> dict[str, Any] | None:
            if not self._semantic_inspection_enabled():
                return None
            try:
                semantic_observation = await figure_semantic_inspection(
                    self._llm_client,
                    question_text=question_text,
                    diagram_description=diagram_description,
                    solve_content=solve_content,
                    figure_goal=goal_result,
                    render_result=render_result,
                    observation=observation,
                )
            except Exception:
                logger.warning("Figure Agent 语义观察失败，接受程序级结果", exc_info=True)
                return None
            if trace is not None:
                trace.record("figure_semantic_observation", semantic_observation)
            return semantic_observation

        async def try_overlay(
            goal_result: dict[str, Any],
            *,
            reason: str,
        ) -> dict[str, Any] | None:
            nonlocal attempt_count
            if not _wants_overlay(goal_result):
                return None
            if self._asset_repo is None or self._settings is None:
                if trace is not None:
                    trace.record("overlay_skipped", {"reason": "asset_context_missing"})
                return None
            if not hasattr(self._asset_repo, "create_asset"):
                if trace is not None:
                    trace.record("overlay_skipped", {"reason": "asset_repository_not_writable"})
                return None
            _asset, image_path, image_base64 = await _load_first_image_asset(
                asset_ids,
                self._asset_repo,
                self._settings,
            )
            if image_path is None or not image_base64:
                if trace is not None:
                    trace.record("overlay_skipped", {"reason": "source_image_missing"})
                return None

            storage = LocalAssetStorage(
                root_dir=getattr(self._settings, "asset_storage_path", "/tmp/studyhelper-assets"),
                base_url=getattr(self._settings, "asset_base_url", "/assets"),
            )
            overlay_auxiliary_text = auxiliary_text or str(
                trigger.get("auxiliary_intent") or ""
            )
            if trace is not None:
                trace.record("auxiliary_text", {"text": overlay_auxiliary_text})

            try:
                target_label = str(
                    goal_result.get("target_diagram")
                    or _infer_target_diagram_label(question_text, diagram_description, solve_content)
                )
                crop_hint: dict[str, Any] = {
                    "label": target_label,
                    "crop_box": [],
                    "confidence": 0.0,
                    "warnings": ["figure_target_crop_vision_skipped"],
                    "usage": {},
                }
                if self._figure_target_crop_vision_enabled():
                    crop_hint = await figure_target_crop(
                        self._llm_client,
                        image_base64=image_base64,
                        question_text=question_text,
                        diagram_description=diagram_description,
                        solve_content=solve_content,
                        figure_goal=goal_result,
                    )
                    target_label = str(crop_hint.get("label") or target_label)
                elif trace is not None:
                    trace.record("target_crop_skipped", {
                        "reason": "figure_target_crop_vision_disabled",
                        "label": target_label,
                    })

                layout_crop_box = infer_layout_crop_box(
                    image_path,
                    target_label=target_label,
                )
                if layout_crop_box:
                    crop_box = layout_crop_box
                    crop_source = "layout_component"
                else:
                    crop_box = crop_hint.get("crop_box")
                    crop_source = "vision_crop_fallback"
                if not crop_box:
                    if trace is not None:
                        trace.record("overlay_skipped", {"reason": "point_location_crop_missing"})
                    return None

                target_diagram = await crop_target_diagram(
                    image_path=image_path,
                    crop_box=crop_box,
                    asset_repository=self._asset_repo,  # type: ignore[arg-type]
                    storage=storage,
                    session_id=session_id,
                    message_id=message_id,
                    label=target_label,
                    display_scale=2,
                )
                target_diagram["source"] = crop_source
                target_diagram["vision"] = {
                    "confidence": crop_hint.get("confidence", 0.0),
                    "warnings": crop_hint.get("warnings", []),
                    "usage": crop_hint.get("usage", {}),
                }
                if trace is not None:
                    trace.record("target_diagram_crop", target_diagram)
                    trace.record("point_location_crop", {
                        "source": crop_source,
                        "label": target_label,
                        "crop_box": target_diagram.get("crop_box"),
                        "width": target_diagram.get("width"),
                        "height": target_diagram.get("height"),
                        "coordinate_space": "crop_pixels",
                        "vision_crop_box": crop_hint.get("crop_box"),
                    })

                crop_path = target_diagram.get("crop_path")
                if not crop_path:
                    if trace is not None:
                        trace.record("overlay_skipped", {"reason": "crop_path_missing"})
                    return None
                crop_base64 = base64.b64encode(Path(crop_path).read_bytes()).decode("ascii")
                point_labels = _overlay_point_labels(
                    question_text,
                    diagram_description,
                    solve_content,
                    goal_result,
                    overlay_auxiliary_text,
                )
                location_result = await figure_point_location(
                    self._llm_client,
                    image_base64=crop_base64,
                    point_labels=point_labels,
                    question_text=question_text,
                    diagram_description=diagram_description,
                    solve_content=solve_content,
                    figure_goal=goal_result,
                )
                localized_points = location_result.get("points", {})
                if trace is not None:
                    trace.record("point_location", {
                        "point_labels": point_labels,
                        "source": crop_source,
                        **location_result,
                    })
                if not localized_points:
                    if trace is not None:
                        trace.record("overlay_skipped", {"reason": "point_location_empty"})
                    return None
                try:
                    snap_result = snap_localized_points_to_geometry(
                        crop_path,
                        localized_points,
                    )
                    if snap_result.get("points"):
                        localized_points = snap_result["points"]
                    if trace is not None:
                        trace.record("point_snap", {
                            "source": "local_cv",
                            **snap_result,
                        })
                except Exception:
                    logger.warning("点位吸附失败，继续使用 VLM 粗坐标", exc_info=True)
                    if trace is not None:
                        trace.record("point_snap", {
                            "source": "local_cv",
                            "points": localized_points,
                            "warnings": ["point_snap_failed"],
                        })

                local_overlay_plan = build_overlay_plan_from_auxiliary_text(overlay_auxiliary_text)
                if local_overlay_plan is not None:
                    overlay_plan = local_overlay_plan
                    overlay_metadata = {
                        "raw_content": "",
                        "usage": {},
                        "scene": "local_overlay_planner",
                        "model": "local",
                    }
                else:
                    overlay_plan, overlay_metadata = await figure_overlay_draw_plan(
                        self._llm_client,
                        question_text=question_text,
                        diagram_description=diagram_description,
                        solve_content=solve_content,
                        figure_goal=goal_result,
                        target_diagram=target_diagram,
                        localized_points=localized_points,
                        auxiliary_text=overlay_auxiliary_text,
                    )
                if trace is not None:
                    trace.record("overlay_plan", {
                        "reason": reason,
                        "plan": overlay_plan,
                        **overlay_metadata,
                    })
                if overlay_plan.get("plan_type") != "overlay_on_crop":
                    if trace is not None:
                        trace.record("overlay_skipped", {
                            "reason": "draw_plan_requested_fallback",
                            "plan": overlay_plan,
                        })
                    return None

                async def render_overlay_attempt(
                    plan_data: dict[str, Any],
                    attempt_reason: str,
                ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
                    nonlocal attempt_count
                    attempt_count += 1
                    try:
                        render_result = await render_overlay_plan(
                            image_path=crop_path,
                            overlay_plan=plan_data,
                            localized_points=localized_points,
                            asset_repository=self._asset_repo,  # type: ignore[arg-type]
                            storage=storage,
                            session_id=session_id,
                            message_id=message_id,
                            display_scale=int(target_diagram.get("display_scale") or 2),
                        )
                        observation = _figure_attempt_observation(
                            source="overlay_renderer",
                            ok=True,
                            details={
                                "render_mode": "overlay_on_crop",
                                "computed_points": render_result.get("computed_points", {}),
                                "warnings": render_result.get("warnings", []),
                            },
                        )
                        if trace is not None:
                            trace.record("overlay_render_trace", {
                                "reason": attempt_reason,
                                "plan": plan_data,
                                "response": render_result,
                                "observation": observation,
                            })
                        return render_result, observation
                    except OverlayRenderError as exc:
                        if trace is not None:
                            trace.record("overlay_render_trace", {
                                "reason": attempt_reason,
                                "plan": plan_data,
                                "observation": exc.observation,
                            })
                        return None, exc.observation
                    except Exception as exc:
                        logger.warning("overlay 渲染失败，回退 Figure Agent", exc_info=True)
                        observation = _figure_attempt_observation(
                            source="overlay_renderer",
                            ok=False,
                            error=str(exc),
                        )
                        if trace is not None:
                            trace.record("overlay_render_trace", {
                                "reason": attempt_reason,
                                "plan": plan_data,
                                "observation": observation,
                            })
                        return None, observation

                def inspect_overlay_programmatically(
                    plan_data: dict[str, Any],
                    render_result: dict[str, Any],
                    attempt_reason: str,
                ) -> dict[str, Any] | None:
                    observation = inspect_overlay_semantics(
                        overlay_plan=plan_data,
                        localized_points=localized_points,
                        render_result=render_result,
                        figure_goal=goal_result,
                        auxiliary_text=overlay_auxiliary_text,
                    )
                    if observation is not None and trace is not None:
                        trace.record("overlay_programmatic_observation", {
                            "reason": attempt_reason,
                            **observation,
                        })
                    return observation

                overlay_result, overlay_observation = await render_overlay_attempt(
                    overlay_plan,
                    reason,
                )
                if overlay_result is not None:
                    programmatic_observation = inspect_overlay_programmatically(
                        overlay_plan,
                        overlay_result,
                        reason,
                    )
                    if programmatic_observation is not None:
                        overlay_observation = {
                            **overlay_observation,
                            "programmatic": programmatic_observation,
                        }
                    else:
                        semantic_observation = await inspect_semantics(
                            goal_result,
                            overlay_result,
                            overlay_observation,
                        )
                        if semantic_observation is None:
                            return overlay_result
                        if semantic_observation.get("next_action") not in {"revise_code", "redraw_plan"}:
                            return overlay_result
                        overlay_observation = {
                            **overlay_observation,
                            "semantic": semantic_observation,
                        }

                if not self._figure_overlay_revision_enabled():
                    if trace is not None:
                        trace.record("overlay_revision_skipped", {
                            "reason": reason,
                            "observation": overlay_observation,
                        })
                    return overlay_result

                revised_plan, revision_metadata = await figure_overlay_revision_plan(
                    self._llm_client,
                    question_text=question_text,
                    diagram_description=diagram_description,
                    solve_content=solve_content,
                    figure_goal=goal_result,
                    target_diagram=target_diagram,
                    localized_points=localized_points,
                    auxiliary_text=overlay_auxiliary_text,
                    previous_plan=overlay_plan,
                    observation=overlay_observation,
                )
                if trace is not None:
                    trace.record("overlay_revision_plan", {
                        "reason": reason,
                        "plan": revised_plan,
                        **revision_metadata,
                    })
                if revised_plan.get("plan_type") != "overlay_on_crop":
                    return overlay_result
                revised_result, _ = await render_overlay_attempt(
                    revised_plan,
                    f"{reason}:revision",
                )
                if revised_result is not None:
                    inspect_overlay_programmatically(
                        revised_plan,
                        revised_result,
                        f"{reason}:revision",
                    )
                return revised_result or overlay_result
            except Exception:
                logger.warning("overlay 优先路径失败，回退 python:figure", exc_info=True)
                if trace is not None:
                    trace.record("overlay_skipped", {"reason": "overlay_path_exception"})
                return None

        async def review_attempt(
            *,
            goal_result: dict[str, Any],
            attempt: FigureAttempt,
            reason: str,
        ) -> tuple[dict[str, Any] | None, bool]:
            result = attempt.get("result")
            observation = attempt.get("observation") or {}
            code = str(attempt.get("code") or "")
            source = str(attempt.get("source") or "figure_agent")

            if trace is not None:
                trace.record("figure_observation", {
                    **observation,
                    "source": source,
                    "reason": reason,
                })

            if result is None:
                if not code:
                    return None, False
                revised_result, _ = await revise_or_redraw(
                    goal_result=goal_result,
                    previous_code=code,
                    observation=observation,
                    reason=f"{reason}:render_error",
                )
                return revised_result, revised_result is not None

            semantic_observation = await inspect_semantics(goal_result, result, observation)
            if semantic_observation is not None:
                next_action = semantic_observation.get("next_action")
                if next_action in {"revise_code", "redraw_plan"}:
                    revised_result, _ = await revise_or_redraw(
                        goal_result=goal_result,
                        previous_code=code,
                        observation={
                            **observation,
                            "source": source,
                            "semantic": semantic_observation,
                        },
                        reason=f"{reason}:semantic:{next_action}",
                    )
                    if revised_result is not None:
                        return revised_result, True
                if next_action == "accept_best_effort":
                    return result, True
                return result, True

            if source == "structured_renderer":
                return None, False

            if observation.get("next_action") == "accept_best_effort":
                return result, True
            if not code:
                return result, True
            revised_result, _ = await revise_or_redraw(
                goal_result=goal_result,
                previous_code=code,
                observation={**observation, "source": source},
                reason=f"{reason}:{observation.get('next_action') or 'review'}",
            )
            if revised_result is not None:
                return revised_result, True
            return result, True

        async def revise_or_redraw(
            *,
            goal_result: dict[str, Any],
            previous_code: str,
            observation: dict[str, Any],
            reason: str,
        ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            if not self._figure_code_revision_enabled():
                if trace is not None:
                    trace.record("figure_revision_skipped", {
                        "reason": reason,
                        "observation": observation,
                    })
                return None, None
            revision_code, revision_metadata = await figure_revision_plan(
                self._llm_client,
                question_text=question_text,
                diagram_description=diagram_description,
                solve_content=solve_content,
                figure_goal=goal_result,
                previous_code=previous_code,
                observation=observation,
            )
            if trace is not None:
                trace.record("figure_revision_plan", {"reason": reason, **revision_metadata})
                trace.record("figure_revision_code", {"reason": reason, "code": revision_code})

            if revision_metadata.get("warning") == "need_redraw_plan":
                redraw_goal = await build_goal(reason=f"{reason}:need_redraw_plan")
                redraw_code = await draw_code(redraw_goal, reason=f"{reason}:need_redraw_plan")
                if not redraw_code:
                    return None, None
                return await render_code(redraw_code, source="draw_plan_llm")

            if not revision_code:
                return None, None
            return await render_code(revision_code, source="revision_llm")

        goal = await build_goal("initial")

        overlay_result = await try_overlay(goal, reason="initial")
        if overlay_result is not None:
            yield _sse_event("figure_result", _figure_result_data(overlay_result, message_id))
            return

        if initial_attempt is not None:
            result, handled = await review_attempt(
                goal_result=goal,
                attempt=initial_attempt,
                reason="structured_candidate",
            )
            if handled and result is not None:
                yield _sse_event("figure_result", _figure_result_data(result, message_id))
                return

        if existing_python_figure and (
            initial_attempt is None or initial_attempt.get("result") is None
        ):
            result, observation = await render_code(
                existing_python_figure,
                source="existing_python_figure",
            )
            legacy_attempt = _figure_attempt(
                source="existing_python_figure",
                code=existing_python_figure,
                result=result,
                observation=observation,
            )
            reviewed_result, handled = await review_attempt(
                goal_result=goal,
                attempt=legacy_attempt,
                reason="existing_python_figure",
            )
            if handled and reviewed_result is not None:
                yield _sse_event("figure_result", _figure_result_data(reviewed_result, message_id))
                return

        code = await draw_code(goal, "initial")

        if not code:
            observation = {
                "execution": {"ok": False, "error": "no_executable_figure_code"},
                "image_quality": {"ok": False, "non_blank": False},
                "security_blocked": False,
                "score": 0,
                "next_action": "redraw_plan",
            }
            if trace is not None:
                trace.record("figure_observation", observation)
            redraw_goal = await build_goal("no_executable_figure_code")
            redraw_code = await draw_code(redraw_goal, "no_executable_figure_code")
            if redraw_code:
                redraw_result, _ = await render_code(redraw_code, source="draw_plan_llm")
                if redraw_result is not None:
                    yield _sse_event("figure_result", _figure_result_data(redraw_result, message_id))
                    return
            if best_result is not None:
                yield _sse_event("figure_result", _figure_result_data(best_result, message_id))
                return
            yield _sse_event("tool_result", {
                "tool": "figure_agent",
                "data": _with_message_id({
                    "status": "failed",
                    "message": "辅助线图暂未生成，但文字解题已完成",
                    "attempt_count": attempt_count,
                }, message_id),
            })
            return

        result, observation = await render_code(code, source="draw_plan_llm")
        if result is not None:
            semantic_observation = await inspect_semantics(goal, result, observation)
            if semantic_observation is None:
                yield _sse_event("figure_result", _figure_result_data(result, message_id))
                return

            next_action = semantic_observation.get("next_action")
            if next_action in {"revise_code", "redraw_plan"}:
                revised_result, _ = await revise_or_redraw(
                    goal_result=goal,
                    previous_code=code,
                    observation={**observation, "semantic": semantic_observation},
                    reason=f"semantic:{next_action}",
                )
                if revised_result is not None:
                    yield _sse_event("figure_result", _figure_result_data(revised_result, message_id))
                    return

            yield _sse_event("figure_result", _figure_result_data(result, message_id))
            return

        revised_result, _ = await revise_or_redraw(
            goal_result=goal,
            previous_code=code,
            observation=observation,
            reason="render_error",
        )
        if revised_result is not None:
            yield _sse_event("figure_result", _figure_result_data(revised_result, message_id))
            return

        if best_result is not None:
            yield _sse_event("figure_result", _figure_result_data(best_result, message_id))
            return

        yield _sse_event("tool_result", {
            "tool": "figure_agent",
            "data": _with_message_id({
                "status": "failed",
                "message": "辅助线图暂未生成，但文字解题已完成",
                "attempt_count": attempt_count,
            }, message_id),
        })

    async def _build_figure_trigger(
        self,
        *,
        question_text: str,
        diagram_description: str,
        solve_content: str,
        auxiliary_text: str,
        existing_python_figure: str | None,
        has_assets: bool,
    ) -> dict[str, Any]:
        if auxiliary_text:
            return _build_local_figure_trigger_payload(
                question_text=question_text,
                diagram_description=diagram_description,
                solve_content=solve_content,
                auxiliary_text=auxiliary_text,
                existing_python_figure=existing_python_figure,
                has_assets=has_assets,
                reason="solve_content_auxiliary_text",
                warning="figure_trigger_llm_skipped",
            )

        if not self._figure_trigger_llm_enabled():
            return _build_local_figure_trigger_payload(
                question_text=question_text,
                diagram_description=diagram_description,
                solve_content=solve_content,
                auxiliary_text="",
                existing_python_figure=existing_python_figure,
                has_assets=has_assets,
                reason="figure_trigger_llm_disabled",
                warning="figure_trigger_llm_disabled",
            )

        warnings: list[str] = []
        try:
            trigger = await figure_trigger(
                self._llm_client,
                question_text=question_text,
                diagram_description=diagram_description,
                solve_content=solve_content,
                existing_python_figure=existing_python_figure,
            )
        except Exception:
            logger.warning("Figure Agent 触发判断失败，使用 fallback", exc_info=True)
            trigger = {}
            warnings.append("trigger_llm_failed")

        for field_name in ("figure_needed", "reason", "auxiliary_intent", "confidence"):
            if field_name not in trigger or trigger.get(field_name) in (None, ""):
                warnings.append(f"{field_name}_missing")
        if _looks_like_geometry_solution(solve_content) and has_assets:
            if not bool(trigger.get("figure_needed")):
                warnings.append("figure_needed_overridden_by_fallback")
            trigger["figure_needed"] = True
            trigger["trigger_source"] = "fallback_geometry_image"
            if not str(trigger.get("reason") or "").strip():
                trigger["reason"] = "fallback: 解答包含几何点线角描述"
        trigger.setdefault("auxiliary_intent", "")
        trigger.setdefault("confidence", 0.0)
        trigger.setdefault("existing_python_figure", existing_python_figure or "")
        if warnings:
            trigger["warnings"] = warnings
        return trigger

    async def _persist_messages(
        self,
        *,
        session_id: str | None,
        user_message: str,
        assistant_content: str,
        plan_result: Any,
        solve_usage: dict[str, int],
        tool_tokens: dict[str, dict[str, int]],
        reflexion_usage: dict[str, int] | None,
        difficulty: str,
    ) -> str | None:
        """持久化用户消息和 AI 回复，返回 assistant message_id。"""
        if not session_id or not self._message_repo:
            return None

        try:
            from app.services.messages import ChatMessageCreate

            # 持久化用户消息
            await self._message_repo.create_message(ChatMessageCreate(
                session_id=session_id,
                role="user",
                content=user_message,
            ))

            # 按层汇总 token 用量
            usage_summary: dict[str, Any] = {
                "planning": plan_result.usage or {},
                "tools": tool_tokens,
                "solving": solve_usage,
                "reflexion": reflexion_usage or {},
                "difficulty": difficulty,
                "strategy": getattr(plan_result, "strategy", ""),
            }

            # 持久化 AI 回复
            result = await self._message_repo.create_message(ChatMessageCreate(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                raw_metadata={"usage": usage_summary},
            ))
            return result.get("message_id") if isinstance(result, dict) else None
        except Exception:
            logger.warning("消息持久化失败", exc_info=True)
            return None
