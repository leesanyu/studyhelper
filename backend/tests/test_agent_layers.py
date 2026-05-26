# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""规划层和执行层单元测试，mock LLMClient。"""

import json
from unittest.mock import AsyncMock

import pytest

from app.agent.layers import (
    PlanResult,
    SolveResult,
    figure_point_location,
    plan,
    solve,
)
from app.agent.llm_client import ChatResponse, StreamEnd, TextDelta
from app.agent.prompts import (
    build_figure_overlay_draw_messages,
    build_point_location_messages,
    build_target_crop_messages,
)


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

    @pytest.mark.asyncio
    async def test_solve_structured_geometry_prompt_does_not_force_python_figure(self):
        """结构化几何解题层不应再强制作图代码。"""
        client = _mock_llm_client_stream(["```python:figure\nplt.plot([0], [0])\n```"])

        await solve(
            client,
            strategy="direct_answer",
            user_message="帮我解这道几何题",
            current_geometry={
                "version": "1.0",
                "observations": {"points": [{"id": "A"}, {"id": "B"}]},
                "given_relations": [],
            },
            tool_results={
                "process_question": (
                    '{"geometry_scene_candidate": {"version": "1.0", '
                    '"observations": {"points": [{"id": "A"}, {"id": "B"}]}}}'
                ),
            },
        )

        call_kwargs = client.stream_chat.call_args[1]
        joined = "\n".join(str(message["content"]) for message in call_kwargs["messages"])
        assert "禁止输出 `python:figure` 代码块" not in joined
        assert "必须生成 Python 绘图代码" not in joined
        assert "注意标记为 python:figure" not in joined
        assert "```python:figure" not in joined
        assert "绘图由后置 Figure Agent" in joined
        assert "【辅助线】" in joined

    @pytest.mark.asyncio
    async def test_solve_structured_geometry_prompt_respects_requested_grade_knowledge(self):
        """结构化几何解答需要按用户指定年级和知识点组织证明。"""
        client = _mock_llm_client_stream(["【辅助线】连接 AB。"])

        await solve(
            client,
            strategy="direct_answer",
            user_message="给出第二问的最终解答，要求使用七年级的全等知识",
            current_geometry={
                "version": "1.0",
                "observations": {"points": [{"id": "A"}, {"id": "B"}]},
                "given_relations": [],
            },
            tool_results={
                "process_question": (
                    '{"geometry_scene_candidate": {"version": "1.0", '
                    '"observations": {"points": [{"id": "A"}, {"id": "B"}]}}}'
                ),
                "extract_knowledge": '{"knowledge_points": ["全等三角形的判定与性质"]}',
            },
        )

        call_kwargs = client.stream_chat.call_args[1]
        joined = "\n".join(str(message["content"]) for message in call_kwargs["messages"])
        assert "用户指定年级" in joined
        assert "全等" in joined
        assert "不得把勾股定理或平方代数作为主证明" in joined

    @pytest.mark.asyncio
    async def test_solve_empty_structured_geometry_does_not_restore_legacy_python_figure_prompt(self):
        """空结构化几何也不能恢复旧的强制 python:figure 提示。"""
        client = _mock_llm_client_stream(["```python:figure\nplt.plot([0], [0])\n```"])

        await solve(
            client,
            strategy="direct_answer",
            user_message="帮我解这道几何题",
            current_geometry={
                "version": "1.0",
                "observations": {"points": []},
                "given_relations": [],
            },
            tool_results={
                "process_question": (
                    '{"geometry_scene_candidate": {"version": "1.0", '
                    '"observations": {"points": []}}}'
                ),
            },
        )

        call_kwargs = client.stream_chat.call_args[1]
        joined = "\n".join(str(message["content"]) for message in call_kwargs["messages"])
        assert "禁止输出 `python:figure` 代码块" not in joined
        assert "必须生成 Python 绘图代码" not in joined
        assert "注意标记为 python:figure" not in joined
        assert "```python:figure" not in joined


class TestFigureOverlayTools:
    """Figure Agent overlay 工具边界测试。"""

    @pytest.mark.asyncio
    async def test_point_location_filters_points_outside_requested_labels(self):
        """点位定位只接受请求的原图点，避免 B' 误入图2 overlay。"""
        client = _mock_llm_client_chat_json(json.dumps({
            "points": {
                "A": {"x": 80, "y": 120, "confidence": 0.95},
                "B'": {"x": 10, "y": 25, "confidence": 0.9},
            },
            "warnings": [],
        }))
        client.model_for_scene = lambda scene: scene

        result = await figure_point_location(
            client,
            image_base64="abc",
            point_labels=["A", "B", "C"],
            question_text="第（2）问",
            diagram_description="图2",
            solve_content="延长 AE 至 F",
            figure_goal={},
        )

        assert result["points"] == {
            "A": {"x": 80, "y": 120, "confidence": 0.95}
        }
        assert "ignored_unrequested_point:B'" in result["warnings"]
        assert client.chat_json.call_args.kwargs["temperature"] == 0.0

    def test_target_crop_prompt_requires_target_diagram_not_text_or_other_figures(self):
        """裁剪 Prompt 必须明确目标是图2几何图，不是题干文字或图1。"""
        messages = build_target_crop_messages(
            image_base64="abc",
            image_size=(3000, 2346),
            question_text="第（2）问，如图2，求证 AH⊥BH",
            diagram_description="含图1、图2和备用图",
            solve_content="延长 AE 至 F",
            figure_goal={
                "target_diagram": "图2",
                "original_figure_elements": ["点A, B, C, D, E, H"],
            },
        )

        joined = "\n".join(str(message["content"]) for message in messages)
        assert "不要截取题干文字" in joined
        assert "不要截取图1" in joined
        assert "必须包含目标图中的已有点标签" in joined
        assert "原图像素尺寸：3000 x 2346" in joined

    def test_point_location_prompt_requires_geometry_points_not_letter_text(self):
        """点位定位 Prompt 必须要求坐标落在几何端点/交点，而不是字母文字本身。"""
        messages = build_point_location_messages(
            image_base64="abc",
            image_size=(830, 832),
            point_labels=["A", "B", "C"],
            question_text="如图2，求证 AH⊥BH",
            diagram_description="图2 包含 A、B、C、D、E、H",
            solve_content="延长 AE 至点 F，使 EF=AE，连接 CF、BF。",
            figure_goal={"target_diagram": "图2"},
        )

        joined = "\n".join(str(message["content"]) for message in messages)
        assert "点位应落在线条交汇或端点处，不要落在字母文字本身" in joined
        assert "裁剪图尺寸：830x832 像素" in joined
        assert "完整解答" not in joined
        assert "Goal Check" not in joined
        assert "延长 AE 至点 F，使 EF=AE，连接 CF、BF" not in joined

    def test_overlay_draw_prompt_requires_supported_operation_schema(self):
        """Draw Prompt 必须给出 renderer 支持的 op schema，减少无效 type/segment 输出。"""
        messages = build_figure_overlay_draw_messages(
            question_text="第（2）问",
            diagram_description="图2",
            solve_content="延长 AE 至点 F，使 EF=AE，连接 CF、BF。",
            figure_goal={},
            target_diagram={},
            localized_points={"A": {"x": 1, "y": 2}, "E": {"x": 3, "y": 2}},
            auxiliary_text="延长 AE 至点 F，使 EF=AE，连接 CF、BF。",
        )

        joined = "\n".join(str(message["content"]) for message in messages)
        assert '"op": "point_on_segment_by_distance"' in joined
        assert '"op": "connect_points"' in joined
        assert "不要输出 type/segment/name/construction 这种自然语言 schema" in joined
