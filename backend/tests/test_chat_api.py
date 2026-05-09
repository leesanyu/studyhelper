# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json

import httpx
import pytest

from app.api.deps import get_chat_service
from app.main import create_app
from app.schemas.chat import ChatCompletionRequest


class FakeChatService:
    async def stream_chat(self, request: ChatCompletionRequest):
        yield {"event": "message_start", "data": {"session_id": request.session_id or "s1"}}
        yield {"event": "delta", "data": {"text": "第一步"}}
        yield {
            "event": "message_end",
            "data": {
                "session_id": request.session_id or "s1",
                "message_id": "m1",
                "dify_message_id": "dify-msg-1",
            },
        }


async def fake_chat_service():
    return FakeChatService()


@pytest.mark.asyncio
async def test_chat_completions_streams_normalized_sse_events():
    app = create_app()
    app.dependency_overrides[get_chat_service] = fake_chat_service
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/completions",
            json={
                "message": "请直接给答案",
                "mode": "direct",
                "asset_ids": ["asset-1"],
                "client_user_id": "anon-1",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    payloads = [json.loads(line.removeprefix("data: ")) for line in lines]

    assert [payload["event"] for payload in payloads] == [
        "message_start",
        "delta",
        "message_end",
    ]
    assert payloads[1]["data"]["text"] == "第一步"
