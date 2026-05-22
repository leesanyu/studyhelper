# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""规划层和执行层逻辑。

规划层：非流式调用 LLM，输出结构化计划 {question_type, strategy, tool_calls, need_deep_reflexion}。
执行层：流式调用 LLM，根据 strategy 生成教学回复，支持实时 delta 回调。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.llm_client import LLMClient, StreamEvent, TextDelta
from app.agent.prompts import build_planning_messages, build_solving_messages


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
