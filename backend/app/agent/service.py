# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent 编排服务：Plan-and-Solve 实时流式调度。

stream_chat(request) → AsyncIterator[SSE_Event]:
  1. yield message_start（立即）
  2. yield thinking(planning) → 调用规划层
  3. 按规划执行工具：yield thinking(tool_exec) → 执行 → yield tool_result
  4. yield thinking(solving) → 调用执行层（实时流式 yield delta）
  5. 解析 python:figure → render_figure → yield figure_result
  6. 反思层检查 → 如有修正 yield reflexion_patch
  7. 持久化消息 → yield message_end
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.agent.layers import SolveResult, plan, _FIGURE_BLOCK_RE
from app.agent.llm_client import LLMClient, TextDelta
from app.agent.prompts import build_solving_messages
from app.agent.reflexion import reflexion_check
from app.agent.tools import KnowledgeResult, QuestionResult, extract_knowledge, process_question
from app.schemas.sandbox import PythonFigureRequest

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


# ── SSE 事件构造 ──────────────────────────────────────────────────


def _sse_event(event: str, data: dict[str, Any] | None = None) -> dict:
    """构造 SSE 事件 dict。"""
    return {"event": event, "data": data or {}}


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
        }
    if tool_name == "extract_knowledge" and isinstance(result, KnowledgeResult):
        return {
            "subject": result.subject,
            "knowledge_points": result.knowledge_points,
            "difficulty": result.difficulty,
            "grade_level": result.grade_level,
        }
    return {}


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
            yield _sse_event("error", {"code": "ai_unavailable", "message": "AI 服务暂时不可用"})
            return

        logger.info("[Plan] question_type=%s strategy=%s tools=%s deep_reflexion=%s",
                    plan_result.question_type, plan_result.strategy,
                    plan_result.tool_calls, plan_result.need_deep_reflexion)

        # 5. 执行工具（按 plan_result.tool_calls 顺序）
        tool_results: dict[str, Any] = {}
        tool_tokens: dict[str, dict[str, int]] = {}
        difficulty = "中等"
        for tool_name in plan_result.tool_calls:
            try:
                if tool_name == "process_question":
                    yield _sse_event("thinking", {"type": "tool_exec", "message": "识别题目中..."})
                    logger.info("[Tool] process_question start has_image=%s", image_base64 is not None)
                    result = await process_question(
                        self._llm_client,
                        image_base64=image_base64,
                        text=message,
                    )
                    tool_results["process_question"] = result
                    if result.usage:
                        tool_tokens["process_question"] = result.usage
                    logger.info("[Tool] process_question done subject=%s has_figure=%s", result.subject, result.has_figure)
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
                        await self._update_session_knowledge(session_id, result)
                        yield _sse_event("tool_result", {
                            "tool": "extract_knowledge",
                            "data": _tool_result_summary("extract_knowledge", result),
                        })
            except Exception:
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
            tool_results=_format_tool_results(tool_results)[1],
        )

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
            yield _sse_event("error", {"code": "ai_unavailable", "message": "AI 服务暂时不可用"})
            return

        full_content = "".join(content_chunks)
        figure_blocks = _FIGURE_BLOCK_RE.findall(full_content)
        logger.info("[Solve] done content_len=%d figures=%d", len(full_content), len(figure_blocks))

        # 7. 处理 python:figure 代码块
        for figure_code in figure_blocks:
            try:
                if self._sandbox_service:
                    request = PythonFigureRequest(code=figure_code, session_id=session_id)
                    fig_result = await self._sandbox_service.render_figure(request)
                    yield _sse_event("figure_result", {
                        "asset_id": fig_result.get("asset_id", ""),
                        "image_url": fig_result.get("image_url", ""),
                    })
            except Exception:
                logger.warning("render_figure 失败，保留代码块文本", exc_info=True)

        # 8. 反思层检查（delta 已发送，反思改为后置非阻塞）
        try:
            reflexion_result = await reflexion_check(
                self._llm_client,
                content=full_content,
                strategy=plan_result.strategy,
                difficulty=difficulty,
                need_deep_reflexion=plan_result.need_deep_reflexion,
            )
            if reflexion_result.had_violation:
                logger.info("[Reflexion] had_violation=True, sending reflexion_patch")
                yield _sse_event("reflexion_patch", {
                    "message": "已修正一处内容问题" if reflexion_result.had_violation else "",
                })
        except Exception:
            logger.warning("[Reflexion] 反思层异常，跳过", exc_info=True)

        # 9. 持久化消息 + Token 用量
        message_id = await self._persist_messages(
            session_id=session_id,
            user_message=message,
            assistant_content=full_content,
            plan_result=plan_result,
            solve_usage=solve_usage,
            tool_tokens=tool_tokens,
            reflexion_usage=None,
            difficulty=difficulty,
        )

        yield _sse_event("message_end", {
            "session_id": session_id or "local-session",
            "message_id": message_id or "",
        })

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
            }
        except Exception:
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
            )
        except Exception:
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
            pass

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
