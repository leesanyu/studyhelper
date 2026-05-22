# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""反思层单元测试。"""

from unittest.mock import AsyncMock

import pytest

from app.agent.llm_client import ChatResponse
from app.agent.reflexion import (
    ReflexionResult,
    _reflex_direct_answer,
    _reflex_socratic,
    _reflex_summarize,
    reflexion_check,
)


class TestLevel1Socratic:
    """引导/拆解模式一级正则检查。"""

    def test_no_leak(self):
        """无泄露时原样返回。"""
        content = "这道题涉及到三角形内角和的性质！\n你能先写出勾股定理的公式吗？"
        result = _reflex_socratic(content)
        assert result.had_violation is False
        assert result.content == content

    def test_detect_answer_is(self):
        """检测"答案是 X"模式。"""
        content = "这道题答案是 60°\n你能理解吗？"
        result = _reflex_socratic(content)
        assert result.had_violation is True
        assert "60°" not in result.content

    def test_detect_so_equals(self):
        """检测"所以 X=5"模式。"""
        content = "所以 ∠C=70°\n请你自己验证一下。"
        result = _reflex_socratic(content)
        assert result.had_violation is True
        assert "70°" not in result.content

    def test_detect_final_result(self):
        """检测"最终结果 为 X"模式。"""
        content = "最终结果为 42\n这就是答案。"
        result = _reflex_socratic(content)
        assert result.had_violation is True

    def test_clean_guidance_passes(self):
        """纯引导无答案时通过。"""
        content = "**思路提示**：直角三角形中，三条边之间有一个著名的关系\n**引导提问**：你还记得勾股定理的公式吗？"
        result = _reflex_socratic(content)
        assert result.had_violation is False


class TestLevel1DirectAnswer:
    """直接解答模式一级正则检查。"""

    def test_has_marker(self):
        """包含"最终答案"标注时通过。"""
        content = "解题过程...\n\n**最终答案**：∠C = 70°"
        result = _reflex_direct_answer(content)
        assert result.had_violation is False

    def test_missing_marker(self):
        """缺少"最终答案"标注时追加提示。"""
        content = "解题过程...\n所以 ∠C = 70°"
        result = _reflex_direct_answer(content)
        assert result.had_violation is True
        assert "最终答案" in result.content


class TestLevel1Summarize:
    """总结/出题模式一级正则检查。"""

    def test_sufficient_points(self):
        """要点>=2 条时通过。"""
        content = "**总结要点**：\n1. 三角形内角和为180°\n2. 已知两角求三角用减法"
        result = _reflex_summarize(content)
        assert result.had_violation is False

    def test_insufficient_points(self):
        """要点不足 2 条时追加提示。"""
        content = "总结：这道题考察了勾股定理"
        result = _reflex_summarize(content)
        assert result.had_violation is True

    def test_similar_question_has_answer(self):
        """相似题包含答案时删除。"""
        content = "1. 三角形内角和\n2. 角度计算\n\n相似题：已知 ∠A=30°，求 ∠B。答案是 60°"
        result = _reflex_summarize(content)
        assert result.had_violation is True
        assert "60°" not in result.content


class TestReflexionEntry:
    """反思层统一入口测试。"""

    @pytest.mark.asyncio
    async def test_level1_only_when_easy(self):
        """容易题且不需要深度反思时，只走一级检查。"""
        llm_client = AsyncMock()

        content = "这道题答案是 60°\n你能理解吗？"
        result = await reflexion_check(
            llm_client,
            content=content,
            strategy="socratic_guide",
            difficulty="中等",
            need_deep_reflexion=False,
        )

        assert isinstance(result, ReflexionResult)
        assert result.had_violation is True
        assert "60°" not in result.content
        # 未触发二级检查
        llm_client.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_level2_triggered_by_difficulty(self):
        """困难题触发二级 LLM 检查。"""
        llm_client = AsyncMock()
        llm_client.chat = AsyncMock(
            return_value=ChatResponse(
                content="修正后的内容（计算有误已修正）", usage={}
            )
        )

        content = "解题过程..."
        result = await reflexion_check(
            llm_client,
            content=content,
            strategy="direct_answer",
            difficulty="困难",
            need_deep_reflexion=False,
        )

        assert result.had_violation is True
        llm_client.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_level2_triggered_by_need_deep(self):
        """need_deep_reflexion=true 触发二级 LLM 检查。"""
        llm_client = AsyncMock()
        llm_client.chat = AsyncMock(
            return_value=ChatResponse(content="没问题，原样输出", usage={})
        )

        content = "正常解答..."
        result = await reflexion_check(
            llm_client,
            content=content,
            strategy="socratic_guide",
            difficulty="中等",
            need_deep_reflexion=True,
        )

        assert isinstance(result, ReflexionResult)
        llm_client.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_level2_no_change_when_correct(self):
        """LLM 自检未发现错误时，认为 had_violation=False。"""
        llm_client = AsyncMock()
        llm_client.chat = AsyncMock(
            return_value=ChatResponse(content="自检通过，内容无误", usage={})
        )

        content = "自检通过，内容无误"
        result = await reflexion_check(
            llm_client,
            content=content,
            strategy="socratic_guide",  # 一级检查不修改内容
            difficulty="困难",
            need_deep_reflexion=True,
        )

        assert result.had_violation is False
        assert result.content == content