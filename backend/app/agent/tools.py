# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent 工具定义：编排层按规划层计划显式调用的子函数。

两个工具：
- process_question：多模态题目解析（图片/文字→结构化题干）
- extract_knowledge：知识点提取（题干→标签+难度）

render_figure 不是工具，而是编排层对执行层输出中 python:figure 代码块的后处理。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.agent.llm_client import LLMClient
from app.agent.prompts import (
    build_extract_knowledge_messages,
    build_process_question_messages,
)


# ── 返回类型定义 ─────────────────────────────────────────────────


@dataclass(frozen=True)
class QuestionResult:
    """题目识别/标准化结果，有图无图输出统一结构。"""

    subject: str
    question_text: str
    has_figure: bool
    diagram_description: str
    question_count: int
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class KnowledgeResult:
    """知识点提取结果。"""

    subject: str
    knowledge_points: list[str]
    difficulty: str
    grade_level: str
    usage: dict[str, int] | None = None


# ── 工具函数 ─────────────────────────────────────────────────────


async def process_question(
    llm_client: LLMClient,
    *,
    image_base64: str | None = None,
    text: str | None = None,
) -> QuestionResult:
    """多模态题目解析：图片/文字→结构化题干。

    有图片时调用视觉模型（llm_model_vision），纯文字时调用题目标准化模型
    （llm_model_question_parse），保证有图无图输出统一结构。
    """
    if not image_base64 and not text:
        raise ValueError("必须提供 image_base64 或 text 至少一项")

    scene = "vision" if image_base64 else "question_parse"
    messages = build_process_question_messages(
        image_base64=image_base64, text=text
    )

    response = await llm_client.chat_json(messages=messages, scene=scene)
    data = json.loads(response.content)

    return QuestionResult(
        subject=data["subject"],
        question_text=data["question_text"],
        has_figure=bool(data.get("has_figure", False)),
        diagram_description=str(data.get("diagram_description", "")),
        question_count=int(data.get("question_count", 1)),
        usage=response.usage or {},
    )


async def extract_knowledge(
    llm_client: LLMClient,
    *,
    question_text: str,
    subject: str,
) -> KnowledgeResult:
    """知识点提取：题干→知识点标签+难度+年级。"""
    messages = build_extract_knowledge_messages(
        question_text=question_text, subject=subject
    )

    response = await llm_client.chat_json(
        messages=messages, scene="knowledge"
    )
    data = json.loads(response.content)

    return KnowledgeResult(
        subject=data["subject"],
        knowledge_points=list(data.get("knowledge_points", [])),
        difficulty=str(data.get("difficulty", "中等")),
        grade_level=str(data.get("grade_level", "")),
        usage=response.usage or {},
    )
