# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from collections.abc import AsyncIterator
from typing import Protocol

from app.schemas.chat import ChatCompletionRequest


class ChatService(Protocol):
    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncIterator[dict]:
        ...


class InMemoryChatService:
    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncIterator[dict]:
        session_id = request.session_id or "local-session"
        yield {"event": "message_start", "data": {"session_id": session_id}}
        yield {"event": "delta", "data": {"text": request.message}}
        yield {"event": "message_end", "data": {"session_id": session_id, "message_id": "local-message"}}


class AgentChatService:
    """Agent 编排聊天服务，委托给 agent/service.py 的 AgentService。"""

    def __init__(self, *, agent_service) -> None:
        self._agent_service = agent_service

    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncIterator[dict]:
        async for event in self._agent_service.stream_chat(
            session_id=request.session_id,
            message=request.message,
            asset_ids=request.asset_ids,
            client_user_id=request.client_user_id,
        ):
            yield event