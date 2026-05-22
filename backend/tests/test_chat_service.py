# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import pytest

from app.schemas.chat import ChatCompletionRequest
from app.services.chat import AgentChatService, InMemoryChatService


class FakeAgentService:
    """Mock AgentService，返回固定事件序列。"""

    def __init__(self, events=None):
        self.events = events or []
        self._calls: list[dict] = []

    async def stream_chat(self, *, session_id=None, message="", asset_ids=None, client_user_id="anonymous"):
        self._calls.append({
            "session_id": session_id,
            "message": message,
            "asset_ids": asset_ids,
            "client_user_id": client_user_id,
        })
        for event in self.events:
            yield event


class TestInMemoryChatService:
    @pytest.mark.asyncio
    async def test_basic_response(self):
        service = InMemoryChatService()
        request = ChatCompletionRequest(session_id="s1", message="你好")
        events = [e async for e in service.stream_chat(request)]
        assert len(events) == 3
        assert events[0]["event"] == "message_start"
        assert events[1]["event"] == "delta"
        assert events[1]["data"]["text"] == "你好"
        assert events[2]["event"] == "message_end"


class TestAgentChatService:
    @pytest.mark.asyncio
    async def test_delegates_to_agent_service(self):
        agent = FakeAgentService(events=[
            {"event": "message_start", "data": {"session_id": "s1"}},
            {"event": "delta", "data": {"text": "同学你好"}},
            {"event": "message_end", "data": {"session_id": "s1", "message_id": "m1"}},
        ])
        service = AgentChatService(agent_service=agent)
        request = ChatCompletionRequest(session_id="s1", message="你好")
        events = [e async for e in service.stream_chat(request)]
        assert len(events) == 3
        assert events[0]["event"] == "message_start"
        assert events[1]["data"]["text"] == "同学你好"

    @pytest.mark.asyncio
    async def test_passes_asset_ids(self):
        agent = FakeAgentService(events=[
            {"event": "delta", "data": {"text": "收到图片"}},
        ])
        service = AgentChatService(agent_service=agent)
        request = ChatCompletionRequest(session_id="s1", message="题目", asset_ids=["asset-1"])
        # consume the stream
        events = [e async for e in service.stream_chat(request)]
        assert len(events) == 1
        assert agent._calls[0]["asset_ids"] == ["asset-1"]
        assert agent._calls[0]["message"] == "题目"