# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import pytest

from app.services.assets import AssetCreate, InMemoryAssetRepository
from app.services.chat import DifyChatService
from app.services.messages import InMemoryChatMessageRepository
from app.schemas.chat import ChatCompletionRequest


class FakeDifyChatClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def stream_chat(self, query, user, conversation_id, files=None, inputs=None):
        self.calls.append(
            {
                "query": query,
                "user": user,
                "conversation_id": conversation_id,
                "files": files,
                "inputs": inputs,
            }
        )
        yield {"event": "message_start", "data": {"conversation_id": "conv-1"}}
        yield {"event": "delta", "data": {"text": "解题步骤"}}
        yield {"event": "message_end", "data": {"dify_message_id": "dify-msg-1"}}


class FakeChatSessionRepository:
    def __init__(self, sessions: dict[str, dict]) -> None:
        self.sessions = sessions
        self.updated_conversations: list[tuple[str, str]] = []

    async def get_session(self, session_id: str) -> dict | None:
        return self.sessions.get(session_id)

    async def update_dify_conversation_id(self, session_id: str, conversation_id: str) -> None:
        self.updated_conversations.append((session_id, conversation_id))
        self.sessions[session_id]["dify_conversation_id"] = conversation_id


@pytest.mark.asyncio
async def test_dify_chat_service_maps_asset_ids_to_dify_file_payload():
    asset_repository = InMemoryAssetRepository()
    await asset_repository.create_asset(
        AssetCreate(
            asset_id="asset-1",
            asset_type="question_image",
            storage_backend="local",
            object_key="uploads/asset-1.png",
            url="/assets/uploads/asset-1.png",
            dify_file_id="dify-file-1",
            filename="question.png",
            mime_type="image/png",
            size_bytes=128,
            width=640,
            height=480,
        )
    )
    dify_client = FakeDifyChatClient()
    service = DifyChatService(dify_client=dify_client, asset_repository=asset_repository)

    events = [
        event
        async for event in service.stream_chat(
            ChatCompletionRequest(
                session_id="session-1",
                message="请直接解答",
                mode="direct",
                asset_ids=["asset-1"],
                client_user_id="anon-1",
            )
        )
    ]

    assert [event["event"] for event in events] == ["message_start", "delta", "message_end"]
    assert dify_client.calls[0]["query"] == "请直接解答"
    assert dify_client.calls[0]["user"] == "anon-1"
    assert dify_client.calls[0]["conversation_id"] is None
    assert dify_client.calls[0]["inputs"] == {"mode": "direct"}
    assert dify_client.calls[0]["files"] == [
        {
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": "dify-file-1",
        }
    ]


@pytest.mark.asyncio
async def test_dify_chat_service_uses_session_conversation_id_when_present():
    dify_client = FakeDifyChatClient()
    service = DifyChatService(
        dify_client=dify_client,
        asset_repository=InMemoryAssetRepository(),
        session_repository=FakeChatSessionRepository(
            {"session-1": {"session_id": "session-1", "dify_conversation_id": "conv-existing"}}
        ),
    )

    events = [
        event
        async for event in service.stream_chat(
            ChatCompletionRequest(
                session_id="session-1",
                message="继续追问",
                mode="guide",
                client_user_id="anon-1",
            )
        )
    ]

    assert dify_client.calls[0]["conversation_id"] == "conv-existing"
    assert events[0]["data"]["session_id"] == "session-1"


@pytest.mark.asyncio
async def test_dify_chat_service_persists_user_and_assistant_messages():
    dify_client = FakeDifyChatClient()
    message_repository = InMemoryChatMessageRepository()
    service = DifyChatService(
        dify_client=dify_client,
        asset_repository=InMemoryAssetRepository(),
        session_repository=FakeChatSessionRepository(
            {"session-1": {"session_id": "session-1", "dify_conversation_id": "conv-existing"}}
        ),
        message_repository=message_repository,
    )

    events = [
        event
        async for event in service.stream_chat(
            ChatCompletionRequest(
                session_id="session-1",
                message="请直接解答",
                mode="direct",
                asset_ids=["asset-1"],
                client_user_id="anon-1",
            )
        )
    ]

    assert [event["event"] for event in events] == ["error"]
    assert message_repository.messages == []

    events = [
        event
        async for event in service.stream_chat(
            ChatCompletionRequest(
                session_id="session-1",
                message="请直接解答",
                mode="direct",
                client_user_id="anon-1",
            )
        )
    ]

    assert [event["event"] for event in events] == ["message_start", "delta", "message_end"]
    assert message_repository.messages[0]["role"] == "user"
    assert message_repository.messages[0]["content"] == "请直接解答"
    assert message_repository.messages[0]["mode"] == "direct"
    assert message_repository.messages[1]["role"] == "assistant"
    assert message_repository.messages[1]["content"] == "解题步骤"
    assert message_repository.messages[1]["dify_message_id"] == "dify-msg-1"


@pytest.mark.asyncio
async def test_dify_chat_service_updates_session_conversation_id_from_stream():
    session_repository = FakeChatSessionRepository(
        {"session-1": {"session_id": "session-1", "dify_conversation_id": None}}
    )
    service = DifyChatService(
        dify_client=FakeDifyChatClient(),
        asset_repository=InMemoryAssetRepository(),
        session_repository=session_repository,
    )

    events = [
        event
        async for event in service.stream_chat(
            ChatCompletionRequest(session_id="session-1", message="新题", client_user_id="anon-1")
        )
    ]

    assert [event["event"] for event in events] == ["message_start", "delta", "message_end"]
    assert session_repository.updated_conversations == [("session-1", "conv-1")]


@pytest.mark.asyncio
async def test_dify_chat_service_returns_error_event_when_asset_is_missing():
    service = DifyChatService(
        dify_client=FakeDifyChatClient(),
        asset_repository=InMemoryAssetRepository(),
    )

    events = [
        event
        async for event in service.stream_chat(
            ChatCompletionRequest(message="继续", asset_ids=["missing-asset"])
        )
    ]

    assert events == [
        {
            "event": "error",
            "data": {
                "code": "asset_not_found",
                "message": "Asset not found: missing-asset",
            },
        }
    ]
