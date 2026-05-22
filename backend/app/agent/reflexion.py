# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""反思层：两级检查——正则必过，LLM 按需触发。

一级（正则，每轮必过，零 LLM 开销）：
- 引导/拆解模式：正则匹配答案泄露，检测到则删除并替换
- 直接解答模式：确认"最终答案"标注
- 总结/出题模式：要点≥2 条 + 相似题不含答案

二级（LLM，按需触发）：
- 触发条件：difficulty=="困难" 或 need_deep_reflexion==True
- 非流式调用 LLM 自检计算过程逻辑一致性
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.llm_client import LLMClient


# ── 一级检查（正则）─────────────────────────────────────────────

# 答案泄露模式：匹配显式给出最终答案的表达
_ANSWER_LEAK_PATTERNS = [
    re.compile(r"答案是\s*[：:，。\s]*\S+"),
    re.compile(r"所以\s*[∠∠△△\w\s\d一-鿿°℃％＝=为是]+\s*[＝=]\s*\S*"),
    re.compile(r"最终\s*(结果|答案)\s*[：:为是]\s*\S+"),
    re.compile(r"故\s*[A-Za-z0-9一-鿿∠△\s°℃]+\s*[＝=]\s*\d+"),
    re.compile(r"因此[，,]?\s*[A-Za-z0-9一-鿿∠△\s°℃]+\s*[＝=为是]\s*\S+"),
]

# 引导替换文本（检测到泄露时替换泄露部分）
_LEAK_REPLACEMENT = "（此处涉及关键答案，请你自己试着推导一下）"

# 直接解答必须包含的标注
_DIRECT_ANSWER_MARKER = "最终答案"

# 总结要点最小数量
_MIN_SUMMARY_POINTS = 2


@dataclass(frozen=True)
class ReflexionResult:
    """反思层输出结果。"""

    content: str
    """反思修正后的文本内容。"""

    had_violation: bool = False
    """是否检测到违规并做了修正。"""

    usage: dict[str, int] | None = None
    """二级 LLM 检查的 token 用量（仅触发时有值）。"""


def _reflex_socratic(content: str) -> ReflexionResult:
    """引导/拆解模式一级检查：检测并处理答案泄露。"""
    modified = content
    had_violation = False
    for pattern in _ANSWER_LEAK_PATTERNS:
        if pattern.search(modified):
            modified = pattern.sub(_LEAK_REPLACEMENT, modified)
            had_violation = True
    return ReflexionResult(content=modified, had_violation=had_violation)


def _reflex_direct_answer(content: str) -> ReflexionResult:
    """直接解答模式一级检查：确认包含"最终答案"标注。"""
    if _DIRECT_ANSWER_MARKER in content:
        return ReflexionResult(content=content, had_violation=False)
    # 追加提示
    fixed = content + "\n\n---\n**最终答案**：请将上述解答中的最终结论在此明确标注。"
    return ReflexionResult(content=fixed, had_violation=True)


def _reflex_summarize(content: str) -> ReflexionResult:
    """总结/出题模式一级检查：要点≥2 条，相似题不含答案。"""
    had_violation = False
    # 检查要点数量（按数字编号或 - 列表项计数）
    point_pattern = re.compile(r"(?:^\d+[\.\、] |^[-*] )", re.MULTILINE)
    points = point_pattern.findall(content)
    modified = content
    if len(points) < _MIN_SUMMARY_POINTS:
        # 在末尾追加提示
        modified += "\n\n（请补充至少 {} 条要点总结）".format(_MIN_SUMMARY_POINTS)
        had_violation = True

    # 检查相似题是否包含答案
    similar_section = re.search(
        r"相似题.*?(?=\n\n|$)", modified, re.DOTALL | re.IGNORECASE
    )
    if similar_section:
        section_text = similar_section.group()
        for pattern in _ANSWER_LEAK_PATTERNS:
            if pattern.search(section_text):
                # 删除相似题中的答案部分
                modified = modified.replace(
                    similar_section.group(),
                    "（相似题请自行练习，答案不在此展示）",
                )
                had_violation = True
                break

    return ReflexionResult(content=modified, had_violation=had_violation)


# strategy → 一级检查函数映射
_LEVEL1_MAP = {
    "socratic_guide": _reflex_socratic,
    "step_breakdown": _reflex_socratic,
    "direct_answer": _reflex_direct_answer,
    "summarize_and_similar": _reflex_summarize,
    "knowledge_lookup": lambda c: ReflexionResult(content=c),
}


# ── 二级检查（LLM）──────────────────────────────────────────────

_REFLEXION_DEEP_PROMPT = """\
你是一位教学质检专家。请检查以下 AI 教学回复是否存在计算错误或逻辑跳跃。

## 检查要点

1. 数学计算是否正确
2. 推理步骤是否有逻辑跳跃（中间结论缺乏依据）
3. 是否与题目给出的已知条件一致
4. 结论是否自洽——前后不能矛盾

## 输出要求

如果发现问题，请输出修正后的完整回复文本。
如果没有问题，请原样输出原文（一字不改）。

## AI 回复原文

{content}

## 修正后的回复（或无问题，原样输出）"""


async def deep_reflexion(
    llm_client: LLMClient,
    content: str,
) -> ReflexionResult:
    """二级 LLM 检查：验证计算过程逻辑一致性。

    仅在 difficulty=="困难" 或 need_deep_reflexion==True 时调用。
    """
    messages = [
        {
            "role": "user",
            "content": _REFLEXION_DEEP_PROMPT.format(content=content),
        }
    ]

    response = await llm_client.chat(
        messages=messages,
        scene="reflexion",
        temperature=0.1,
    )

    corrected = response.content.strip()
    usage = response.usage or {}
    # 如果输出和原内容几乎相同（允许微小差异），视为未发现错误
    if _texts_roughly_equal(corrected, content):
        return ReflexionResult(content=content, had_violation=False, usage=usage)

    return ReflexionResult(content=corrected, had_violation=True, usage=usage)


def _texts_roughly_equal(a: str, b: str, threshold: float = 0.95) -> bool:
    """判断两段文本是否几乎相同（基于 SequenceMatcher 相似度）。"""
    if not a or not b:
        return False
    import difflib
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio >= threshold


# ── 统一入口 ────────────────────────────────────────────────────


async def reflexion_check(
    llm_client: LLMClient,
    content: str,
    strategy: str,
    *,
    difficulty: str = "中等",
    need_deep_reflexion: bool = False,
) -> ReflexionResult:
    """反思层统一入口。

    一级正则检查（每轮必过），二级 LLM 按需触发。
    """
    # 一级：正则检查
    level1_fn = _LEVEL1_MAP.get(strategy, lambda c: ReflexionResult(content=c))
    result = level1_fn(content)

    # 二级：LLM 按需触发
    if difficulty == "困难" or need_deep_reflexion:
        return await deep_reflexion(llm_client, result.content)

    return result