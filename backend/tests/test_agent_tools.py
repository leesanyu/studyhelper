# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent 工具定义单元测试，mock LLMClient。"""

import json
from unittest.mock import AsyncMock

import pytest

from app.agent.llm_client import ChatResponse
from app.agent.tools import (
    KnowledgeResult,
    QuestionResult,
    extract_knowledge,
    process_question,
)


def _mock_llm_client(response_content: str) -> AsyncMock:
    """创建返回指定内容的 mock LLMClient。"""
    client = AsyncMock()
    client.chat_json = AsyncMock(
        return_value=ChatResponse(content=response_content, usage={})
    )
    return client


class TestProcessQuestion:
    """process_question 工具测试。"""

    @pytest.mark.asyncio
    async def test_process_question_with_image(self):
        """有图片时调用 vision 场景，返回 QuestionResult。"""
        response_json = json.dumps({
            "subject": "初中数学",
            "question_text": "在△ABC中，∠A=60°，∠B=50°，求∠C的度数",
            "has_figure": True,
            "diagram_description": "三角形ABC，∠A标注60°，∠B标注50°",
            "question_count": 1,
        })
        client = _mock_llm_client(response_json)

        result = await process_question(
            client, image_base64="iVBOR...", text="帮我看看这道题"
        )

        assert isinstance(result, QuestionResult)
        assert result.subject == "初中数学"
        assert "∠C" in result.question_text
        assert result.has_figure is True
        assert "三角形" in result.diagram_description
        assert result.question_count == 1

        # 验证调用 vision 场景
        call_kwargs = client.chat_json.call_args[1]
        assert call_kwargs["scene"] == "vision"

    @pytest.mark.asyncio
    async def test_process_question_text_only(self):
        """纯文字时调用 question_parse 场景，返回 QuestionResult。"""
        response_json = json.dumps({
            "subject": "高中数学",
            "question_text": "求函数 $f(x) = x^2 - 2x + 1$ 的最小值",
            "has_figure": False,
            "diagram_description": "",
            "question_count": 1,
        })
        client = _mock_llm_client(response_json)

        result = await process_question(
            client, text="求函数f(x)=x^2-2x+1的最小值"
        )

        assert result.subject == "高中数学"
        assert result.has_figure is False
        assert result.diagram_description == ""

        # 验证调用 question_parse 场景
        call_kwargs = client.chat_json.call_args[1]
        assert call_kwargs["scene"] == "question_parse"

    @pytest.mark.asyncio
    async def test_process_question_no_input_raises(self):
        """不提供 image_base64 和 text 时抛出 ValueError。"""
        client = _mock_llm_client("{}")

        with pytest.raises(ValueError, match="必须提供"):
            await process_question(client)

    @pytest.mark.asyncio
    async def test_process_question_image_only(self):
        """仅图片无文字时正确调用。"""
        response_json = json.dumps({
            "subject": "初中数学",
            "question_text": "计算∠A的度数",
            "has_figure": True,
            "diagram_description": "三角形ABC",
            "question_count": 1,
        })
        client = _mock_llm_client(response_json)

        result = await process_question(client, image_base64="iVBOR...")

        assert result.subject == "初中数学"
        assert result.has_figure is True

        # 验证 messages 包含 image_url
        call_kwargs = client.chat_json.call_args[1]
        user_msg = call_kwargs["messages"][1]
        assert user_msg["role"] == "user"
        content = user_msg["content"]
        assert isinstance(content, list)
        assert any(item.get("type") == "image_url" for item in content)


class TestExtractKnowledge:
    """extract_knowledge 工具测试。"""

    @pytest.mark.asyncio
    async def test_extract_knowledge_basic(self):
        """基本知识点提取返回 KnowledgeResult。"""
        response_json = json.dumps({
            "subject": "初中数学",
            "knowledge_points": ["三角形内角和", "角度计算"],
            "difficulty": "简单",
            "grade_level": "七年级",
        })
        client = _mock_llm_client(response_json)

        result = await extract_knowledge(
            client,
            question_text="在△ABC中，∠A=60°，∠B=50°，求∠C的度数",
            subject="初中数学",
        )

        assert isinstance(result, KnowledgeResult)
        assert result.subject == "初中数学"
        assert len(result.knowledge_points) == 2
        assert "三角形内角和" in result.knowledge_points
        assert result.difficulty == "简单"
        assert result.grade_level == "七年级"

        # 验证调用 knowledge 场景
        call_kwargs = client.chat_json.call_args[1]
        assert call_kwargs["scene"] == "knowledge"

    @pytest.mark.asyncio
    async def test_extract_knowledge_with_empty_grade(self):
        """年级信息为空时正确处理。"""
        response_json = json.dumps({
            "subject": "高中数学",
            "knowledge_points": ["二次函数最值", "配方法"],
            "difficulty": "简单",
            "grade_level": "",
        })
        client = _mock_llm_client(response_json)

        result = await extract_knowledge(
            client,
            question_text="求函数f(x)=x²-2x+1的最小值",
            subject="高中数学",
        )

        assert result.grade_level == ""
        assert len(result.knowledge_points) == 2

    @pytest.mark.asyncio
    async def test_extract_knowledge_messages_format(self):
        """验证传给 LLM 的 messages 格式正确。"""
        response_json = json.dumps({
            "subject": "初中数学",
            "knowledge_points": ["勾股定理"],
            "difficulty": "中等",
            "grade_level": "八年级",
        })
        client = _mock_llm_client(response_json)

        await extract_knowledge(
            client,
            question_text="已知直角三角形两直角边长分别为3和4",
            subject="初中数学",
        )

        call_kwargs = client.chat_json.call_args[1]
        messages = call_kwargs["messages"]
        # system + user 两条消息
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "初中数学" in messages[1]["content"]
        assert "直角三角形" in messages[1]["content"]
