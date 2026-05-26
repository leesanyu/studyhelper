# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""OpenAI 兼容 LLM 客户端，基于 openai SDK（AsyncOpenAI）。

支持三种调用模式：
- 流式聊天：stream_chat → AsyncIterator[StreamEvent]
- 非流式聊天：chat → ChatResponse（支持 JSON Mode）
- Vision 聊天：通过 messages 中 image_url 类型传入图片 base64

模型配置采用"默认供应商 + 按模型可选覆盖"设计，
url = model_xxx_url or llm_api_url，key = model_xxx_key or llm_api_key。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings


# ── StreamEvent 类型定义 ──────────────────────────────────────────


@dataclass(frozen=True)
class TextDelta:
    """流式输出的增量文本片段"""

    text: str


@dataclass(frozen=True)
class StreamEnd:
    """流式输出结束标记"""

    usage: dict[str, int] | None = None


# StreamEvent 联合类型
StreamEvent = TextDelta | StreamEnd


# ── ChatResponse 类型定义 ────────────────────────────────────────


@dataclass(frozen=True)
class ChatResponse:
    """非流式聊天响应"""

    content: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any = None


# ── 模型配置解析 ─────────────────────────────────────────────────

# 场景名称到 Settings 属性前缀的映射
_MODEL_SCENES = (
    "planning",
    "question_parse",
    "solving",
    "reflexion",
    "vision",
    "knowledge",
    "figure_trigger",
    "figure_goal",
    "figure_draw",
    "figure_revision",
    "figure_semantic_inspection",
)


def _resolve_model_config(
    settings: Settings, scene: str
) -> tuple[str, str, str]:
    """解析指定场景的模型配置，返回 (model_name, base_url, api_key)。

    优先使用场景专属的 _url/_key，未配置则 fallback 到默认值。
    """
    model_name: str = getattr(settings, f"llm_model_{scene}")
    override_url: str | None = getattr(settings, f"llm_model_{scene}_url")
    override_key: str | None = getattr(settings, f"llm_model_{scene}_key")
    return (
        model_name,
        override_url or settings.llm_api_url,
        override_key or settings.llm_api_key,
    )


# ── LLMClient ────────────────────────────────────────────────────


class LLMClient:
    """OpenAI 兼容 LLM 客户端，封装 AsyncOpenAI，按场景选择模型和供应商。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # 按场景缓存 AsyncOpenAI 实例（同一 base_url+api_key 共享客户端）
        self._clients: dict[str, AsyncOpenAI] = {}

    def _get_client(self, scene: str) -> AsyncOpenAI:
        """获取或创建指定场景的 AsyncOpenAI 客户端实例。

        同一 (base_url, api_key) 组合共享客户端以复用连接池。
        """
        model_name, base_url, api_key = _resolve_model_config(
            self._settings, scene
        )
        cache_key = f"{base_url}:{api_key}"
        if cache_key not in self._clients:
            self._clients[cache_key] = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                max_retries=2,
            )
        return self._clients[cache_key]

    def _get_model(self, scene: str) -> str:
        """获取指定场景的模型名称。"""
        model_name, _, _ = _resolve_model_config(self._settings, scene)
        return model_name

    def model_for_scene(self, scene: str) -> str:
        """暴露指定场景的模型名称，供 trace 记录。"""
        return self._get_model(scene)

    # ── 非流式聊天 ───────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        scene: str = "planning",
        *,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.3,
    ) -> ChatResponse:
        """非流式聊天，用于规划层、工具调用和反思层。

        Args:
            messages: OpenAI 格式消息列表
            scene: 模型场景，决定使用哪个模型和供应商
            response_format: 可选，如 {"type": "json_object"} 启用 JSON Mode
            temperature: 生成温度
        """
        client = self._get_client(scene)
        model = self._get_model(scene)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        response = await client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return ChatResponse(content=content, usage=usage, raw_response=response)

    # ── 流式聊天 ─────────────────────────────────────────────────

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        scene: str = "solving",
        *,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamEvent]:
        """流式聊天，用于执行层教学回复生成。

        Args:
            messages: OpenAI 格式消息列表（支持 image_url 类型）
            scene: 模型场景，决定使用哪个模型和供应商
            temperature: 生成温度
        """
        client = self._get_client(scene)
        model = self._get_model(scene)

        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )

        async for chunk in stream:
            # 处理 usage 信息（最后一个 chunk）
            if chunk.usage is not None:
                yield StreamEnd(
                    usage={
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }
                )
                continue

            # 处理 delta 文本
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield TextDelta(text=delta.content)

    # ── 便捷方法 ─────────────────────────────────────────────────

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        scene: str = "planning",
        *,
        temperature: float = 0.1,
    ) -> ChatResponse:
        """非流式聊天 + JSON Mode，用于规划层、知识点提取等结构化输出场景。"""
        return await self.chat(
            messages,
            scene,
            response_format={"type": "json_object"},
            temperature=temperature,
        )
