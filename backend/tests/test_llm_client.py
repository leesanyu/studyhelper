# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""LLM 客户端单元测试，mock openai SDK。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.llm_client import (
    ChatResponse,
    LLMClient,
    StreamEnd,
    TextDelta,
    _resolve_model_config,
)
from app.core.config import Settings


# ── 测试用的 Settings 工厂 ──────────────────────────────────────


def _make_settings(**overrides) -> Settings:
    """创建测试用 Settings，覆盖指定字段。"""
    defaults = {
        "llm_api_url": "https://api.example.com/v1",
        "llm_api_key": "sk-test-key",
        "llm_model_planning": "qwen3.6-plus",
        "llm_model_planning_url": None,
        "llm_model_planning_key": None,
        "llm_model_question_parse": "qwen3.6-plus",
        "llm_model_question_parse_url": None,
        "llm_model_question_parse_key": None,
        "llm_model_solving": "qwen3.6-plus",
        "llm_model_solving_url": None,
        "llm_model_solving_key": None,
        "llm_model_reflexion": "qwen3.6-plus",
        "llm_model_reflexion_url": None,
        "llm_model_reflexion_key": None,
        "llm_model_vision": "qwen-vl-max-latest",
        "llm_model_vision_url": None,
        "llm_model_vision_key": None,
        "llm_model_knowledge": "qwen3.6-plus",
        "llm_model_knowledge_url": None,
        "llm_model_knowledge_key": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── _resolve_model_config 测试 ──────────────────────────────────


class TestResolveModelConfig:
    """模型配置解析测试。"""

    def test_default_config(self):
        """未覆盖时，所有场景使用默认 url 和 key。"""
        settings = _make_settings()
        model, url, key = _resolve_model_config(settings, "planning")
        assert model == "qwen3.6-plus"
        assert url == "https://api.example.com/v1"
        assert key == "sk-test-key"

    def test_vision_model_different(self):
        """vision 场景使用不同的模型名。"""
        settings = _make_settings()
        model, url, key = _resolve_model_config(settings, "vision")
        assert model == "qwen-vl-max-latest"
        assert url == "https://api.example.com/v1"
        assert key == "sk-test-key"

    def test_override_url_and_key(self):
        """场景专属 url/key 覆盖默认值。"""
        settings = _make_settings(
            llm_model_solving="deepseek-chat",
            llm_model_solving_url="https://api.deepseek.com/v1",
            llm_model_solving_key="sk-deepseek-key",
        )
        model, url, key = _resolve_model_config(settings, "solving")
        assert model == "deepseek-chat"
        assert url == "https://api.deepseek.com/v1"
        assert key == "sk-deepseek-key"

    def test_override_url_only(self):
        """仅覆盖 url 时，key 使用默认值。"""
        settings = _make_settings(
            llm_model_solving_url="https://api.deepseek.com/v1",
        )
        model, url, key = _resolve_model_config(settings, "solving")
        assert url == "https://api.deepseek.com/v1"
        assert key == "sk-test-key"

    def test_non_overridden_scene_uses_default(self):
        """覆盖 solving 不影响其他场景。"""
        settings = _make_settings(
            llm_model_solving="deepseek-chat",
            llm_model_solving_url="https://api.deepseek.com/v1",
            llm_model_solving_key="sk-deepseek-key",
        )
        model, url, key = _resolve_model_config(settings, "planning")
        assert model == "qwen3.6-plus"
        assert url == "https://api.example.com/v1"
        assert key == "sk-test-key"


# ── LLMClient 测试 ──────────────────────────────────────────────


class TestLLMClientChat:
    """非流式聊天测试。"""

    @pytest.mark.asyncio
    async def test_chat_basic(self):
        """基本非流式聊天返回正确内容。"""
        settings = _make_settings()
        client = LLMClient(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "你好，同学！"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=mock_response
            )
            mock_get_client.return_value = mock_openai

            result = await client.chat(
                messages=[{"role": "user", "content": "你好"}],
                scene="planning",
            )

        assert isinstance(result, ChatResponse)
        assert result.content == "你好，同学！"
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5

    @pytest.mark.asyncio
    async def test_chat_json_mode(self):
        """JSON Mode 调用传入 response_format。"""
        settings = _make_settings()
        client = LLMClient(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"status": "ok"}'
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10
        mock_response.usage.total_tokens = 30

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=mock_response
            )
            mock_get_client.return_value = mock_openai

            result = await client.chat_json(
                messages=[{"role": "user", "content": "分析"}],
                scene="planning",
            )

        # 验证 response_format 被传入
        call_kwargs = mock_openai.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert result.content == '{"status": "ok"}'

    @pytest.mark.asyncio
    async def test_chat_uses_correct_scene(self):
        """不同场景使用不同的模型名。"""
        settings = _make_settings()
        client = LLMClient(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 0
        mock_response.usage.completion_tokens = 0
        mock_response.usage.total_tokens = 0

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=mock_response
            )
            mock_get_client.return_value = mock_openai

            await client.chat(
                messages=[{"role": "user", "content": "看图"}],
                scene="vision",
            )

        call_kwargs = mock_openai.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "qwen-vl-max-latest"


class TestLLMClientStreamChat:
    """流式聊天测试。"""

    @pytest.mark.asyncio
    async def test_stream_chat_basic(self):
        """基本流式聊天产生 TextDelta 和 StreamEnd 事件。"""
        settings = _make_settings()
        client = LLMClient(settings)

        # 构造 mock 流式响应
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "你好"
        chunk1.usage = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "，同学"
        chunk2.usage = None

        chunk3 = MagicMock()
        chunk3.choices = []
        chunk3.usage = MagicMock()
        chunk3.usage.prompt_tokens = 10
        chunk3.usage.completion_tokens = 8
        chunk3.usage.total_tokens = 18

        chunks = [chunk1, chunk2, chunk3]

        # 构造异步迭代器
        class AsyncChunkIterator:
            def __init__(self, items):
                self._items = iter(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._items)
                except StopIteration:
                    raise StopAsyncIteration

        mock_stream = AsyncChunkIterator(chunks)

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_get_client.return_value = mock_openai

            events = []
            async for event in client.stream_chat(
                messages=[{"role": "user", "content": "你好"}],
                scene="solving",
            ):
                events.append(event)

        assert len(events) == 3
        assert isinstance(events[0], TextDelta)
        assert events[0].text == "你好"
        assert isinstance(events[1], TextDelta)
        assert events[1].text == "，同学"
        assert isinstance(events[2], StreamEnd)
        assert events[2].usage["total_tokens"] == 18


class TestLLMClientClientCaching:
    """客户端实例缓存测试。"""

    def test_same_url_key_shares_client(self):
        """相同 base_url + api_key 的场景共享同一个 AsyncOpenAI 实例。"""
        settings = _make_settings()
        client = LLMClient(settings)

        c1 = client._get_client("planning")
        c2 = client._get_client("solving")
        assert c1 is c2

    def test_different_url_gets_different_client(self):
        """不同 base_url 的场景使用不同的 AsyncOpenAI 实例。"""
        settings = _make_settings(
            llm_model_solving_url="https://api.deepseek.com/v1",
            llm_model_solving_key="sk-deepseek",
        )
        client = LLMClient(settings)

        c1 = client._get_client("planning")
        c2 = client._get_client("solving")
        assert c1 is not c2


class TestLLMClientVisionMessages:
    """Vision 消息格式测试。"""

    @pytest.mark.asyncio
    async def test_vision_messages_passed_through(self):
        """包含 image_url 的消息正确传递给 SDK。"""
        settings = _make_settings()
        client = LLMClient(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "这是一道数学题"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 120

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请识别这道题"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,iVBOR..."
                        },
                    },
                ],
            }
        ]

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=mock_response
            )
            mock_get_client.return_value = mock_openai

            result = await client.chat(
                messages=messages,
                scene="vision",
            )

        call_kwargs = mock_openai.chat.completions.create.call_args[1]
        assert call_kwargs["messages"] == messages
        assert call_kwargs["model"] == "qwen-vl-max-latest"
        assert result.content == "这是一道数学题"
