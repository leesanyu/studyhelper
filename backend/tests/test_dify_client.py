# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json

import httpx
import pytest

from app.services.dify import DifyClient


@pytest.mark.asyncio
async def test_dify_client_normalizes_streaming_chat_events():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/chat-messages"
        chunks = [
            {"event": "message", "answer": "第一", "message_id": "m1", "conversation_id": "c1"},
            {"event": "message", "answer": "步", "message_id": "m1", "conversation_id": "c1"},
            {"event": "message_end", "message_id": "m1", "conversation_id": "c1"},
        ]
        content = "".join(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks)
        return httpx.Response(200, content=content.encode("utf-8"))

    client = DifyClient(
        api_url="http://dify.test",
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    events = [
        event
        async for event in client.stream_chat(
            query="题目",
            user="anon-1",
            conversation_id=None,
            files=[{"type": "image", "transfer_method": "local_file", "upload_file_id": "file-1"}],
        )
    ]

    assert [event["event"] for event in events] == ["message_start", "delta", "delta", "message_end"]
    assert events[0]["data"]["conversation_id"] == "c1"
    assert events[1]["data"]["text"] == "第一"
    assert events[3]["data"]["dify_message_id"] == "m1"


@pytest.mark.asyncio
async def test_dify_client_uploads_file_and_returns_file_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/files/upload"
        return httpx.Response(200, json={"id": "file-1", "name": "question.png"})

    client = DifyClient(
        api_url="http://dify.test",
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.upload_file(
        filename="question.png",
        content=b"image-bytes",
        mime_type="image/png",
        user="anon-1",
    )

    assert result["id"] == "file-1"
