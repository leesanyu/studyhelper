# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""规划层和执行层单元测试，mock LLMClient。"""

import json
from unittest.mock import AsyncMock

import pytest

from app.agent.layers import PlanResult, SolveResult, plan, solve
from app.agent.llm_client import ChatResponse, StreamEnd, TextDelta


def _mock_llm_client_chat_json(response_content):
    """创建 chat_json 返回指定内容的 mock。"""
    client = AsyncMock()
    client.chat_json = AsyncMock(
        return_value=ChatResponse(content=response_content, usage={})
    )
    return client


class _AsyncChunkIterator:
    """异步迭代器，用于 mock stream_chat 的流式响应。"""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def _mock_llm_client_stream(chunks):
    """创建 stream_chat 返回指定文本片段的 mock。

    stream_chat 是 async generator，调用时直接返回 async iterator，
    不需要 await。因此不能用 AsyncMock（它返回 coroutine），
    需要设为返回 async iterator 的可调用对象，同时记录调用参数。
    """
    client = AsyncMock()
    events = [TextDelta(text=chunk) for chunk in chunks]
    events.append(
        StreamEnd(
            usage={"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}
        )
    )

    class StreamChatMock:
        """支持 call_args 追踪的 stream_chat mock。"""
        def __init__(self):
            self.call_args = None
            self.call_count = 0

        def __call__(self, *args, **kwargs):
            self.call_args = (args, kwargs)
            self.call_count += 1
            return _AsyncChunkIterator(events)

    client.stream_chat = StreamChatMock()
    return client


class TestPlan:
    """规划层逻辑测试。"""

    @pytest.mark.asyncio
    async def test_plan_with_new_question(self):
        """新题目时规划层输出 logical_calculation + socratic_guide。"""
        response_json = json.dumps({
            "question_type": "logical_calculation",
            "strategy": "socratic_guide",
            "tool_calls": ["process_question", "extract_knowledge"],
            "need_deep_reflexion": False,
        })
        client = _mock_llm_client_chat_json(response_json)

        result = await plan(
            client,
            user_message="在△ABC中，∠A=60°，∠B=50°，求∠C",
        )

        assert isinstance(result, PlanResult)
        assert result.question_type == "logical_calculation"
        assert result.strategy == "socratic_guide"
        assert result.tool_calls == ["process_question", "extract_knowledge"]
        assert result.need_deep_reflexion is False

    @pytest.mark.asyncio
    async def test_plan_with_image_summary(self):
        """有图片摘要时规划层决定调用 process_question。"""
        response_json = json.dumps({
            "question_type": "logical_calculation",
            "strategy": "socratic_guide",
            "tool_calls": ["process_question", "extract_knowledge"],
            "need_deep_reflexion": False,
        })
        client = _mock_llm_client_chat_json(response_json)

        result = await plan(
            client,
            user_message="帮我看看这道题",
            image_summary="[用户上传了一张包含数学题目的图片，300KB]",
        )

        assert "process_question" in result.tool_calls

        # 验证 messages 中包含图片摘要
        call_kwargs = client.chat_json.call_args[1]
        last_msg = call_kwargs["messages"][-1]
        assert "数学题目的图片" in last_msg["content"]

    @pytest.mark.asyncio
    async def test_plan_continue_dialogue(self):
        """继续对话时无需调用工具。"""
        response_json = json.dumps({
            "question_type": "continue_dialogue",
            "strategy": "step_breakdown",
            "tool_calls": [],
            "need_deep_reflexion": False,
        })
        client = _mock_llm_client_chat_json(response_json)

        result = await plan(
            client,
            user_message="我还是不太理解",
            current_question="在△ABC中，∠A=60°，∠B=50°，求∠C",
        )

        assert result.question_type == "continue_dialogue"
        assert result.strategy == "step_breakdown"
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_plan_direct_answer_request(self):
        """学生要求直接答案时策略为 direct_answer。"""
        response_json = json.dumps({
            "question_type": "direct_answer_request",
            "strategy": "direct_answer",
            "tool_calls": [],
            "need_deep_reflexion": False,
        })
        client = _mock_llm_client_chat_json(response_json)

        result = await plan(
            client,
            user_message="直接告诉我答案吧",
            current_question="在△ABC中，∠A=60°，∠B=50°，求∠C",
        )

        assert result.strategy == "direct_answer"

    @pytest.mark.asyncio
    async def test_plan_user_frustration(self):
        """学生表达不满时 need_deep_reflexion 为 true。"""
        response_json = json.dumps({
            "question_type": "continue_dialogue",
            "strategy": "step_breakdown",
            "tool_calls": [],
            "need_deep_reflexion": True,
        })
        client = _mock_llm_client_chat_json(response_json)

        result = await plan(
            client,
            user_message="不对，还是错的",
            current_question="在△ABC中，∠A=60°，∠B=50°，求∠C",
        )

        assert result.need_deep_reflexion is True

    @pytest.mark.asyncio
    async def test_plan_json_parse_failure_fallback(self):
        """JSON 解析失败时 fallback 为默认策略。"""
        client = _mock_llm_client_chat_json("这不是合法JSON")

        result = await plan(client, user_message="你好")

        assert result.question_type == "continue_dialogue"
        assert result.strategy == "socratic_guide"
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_plan_with_context_in_messages(self):
        """有题目上下文时规划层 messages 包含上下文信息。"""
        response_json = json.dumps({
            "question_type": "continue_dialogue",
            "strategy": "socratic_guide",
            "tool_calls": [],
            "need_deep_reflexion": False,
        })
        client = _mock_llm_client_chat_json(response_json)

        await plan(
            client,
            user_message="然后呢",
            current_question="求∠C的度数",
            current_knowledge={"knowledge_points": ["三角形内角和"]},
            current_diagram="三角形ABC",
        )

        call_kwargs = client.chat_json.call_args[1]
        last_msg = call_kwargs["messages"][-1]
        assert "求∠C的度数" in last_msg["content"]


class TestSolve:
    """执行层逻辑测试。"""

    @pytest.mark.asyncio
    async def test_solve_basic(self):
        """基本执行层输出。"""
        client = _mock_llm_client_stream([
            "这道题涉及到三角形内角和",
            "的一个重要性质！",
        ])

        result = await solve(
            client,
            strategy="socratic_guide",
            user_message="在△ABC中，∠A=60°，∠B=50°，求∠C",
        )

        assert isinstance(result, SolveResult)
        assert "三角形内角和" in result.content
        assert result.figure_blocks == []
        assert result.usage["total_tokens"] == 300

    @pytest.mark.asyncio
    async def test_solve_with_figure_block(self):
        """执行层输出包含 python:figure 代码块时正确解析。"""
        figure_code = (
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1,2],[3,4])\n"
            "plt.savefig('figure.png')"
        )
        content = (
            "我们来看这道题的图形：\n\n"
            f"```python:figure\n{figure_code}```\n\n"
            "你能看出什么规律吗？"
        )
        client = _mock_llm_client_stream([content])

        result = await solve(
            client,
            strategy="socratic_guide",
            user_message="看这道几何题",
        )

        assert len(result.figure_blocks) == 1
        assert "matplotlib" in result.figure_blocks[0]

    @pytest.mark.asyncio
    async def test_solve_uses_solving_scene(self):
        """执行层使用 solving 场景。"""
        client = _mock_llm_client_stream(["好的"])

        await solve(
            client,
            strategy="socratic_guide",
            user_message="帮我看看",
        )

        call_kwargs = client.stream_chat.call_args[1]
        assert call_kwargs["scene"] == "solving"

    @pytest.mark.asyncio
    async def test_solve_strategy_in_system_prompt(self):
        """执行层 system prompt 中包含当前策略。"""
        client = _mock_llm_client_stream(["好的"])

        await solve(
            client,
            strategy="direct_answer",
            user_message="直接告诉我答案",
        )

        call_kwargs = client.stream_chat.call_args[1]
        system_msg = call_kwargs["messages"][0]
        assert "direct_answer" in system_msg["content"]

    @pytest.mark.asyncio
    async def test_solve_with_tool_results(self):
        """工具执行结果传入执行层 messages。"""
        client = _mock_llm_client_stream(["这道题是关于..."])

        await solve(
            client,
            strategy="socratic_guide",
            user_message="帮我看看这道题",
            tool_results={
                "process_question": '{"subject": "初中数学", "question_text": "求∠C"}',
            },
        )

        call_kwargs = client.stream_chat.call_args[1]
        last_msg = call_kwargs["messages"][-1]
        assert "process_question" in last_msg["content"]
