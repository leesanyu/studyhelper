# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import httpx
import pytest

from app.api.deps import get_session_service
from app.main import create_app
from app.schemas.sessions import SessionCreateRequest
from app.services.messages import ChatMessageCreate
from app.services.sessions import InMemorySessionService


@pytest.mark.asyncio
async def test_sessions_can_be_created_listed_and_read():
    app = create_app()
    session_service = InMemorySessionService()

    async def fake_session_service():
        return session_service

    app.dependency_overrides[get_session_service] = fake_session_service
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/sessions",
            json={"client_user_id": "anon-1", "title": "几何题", "asset_ids": ["asset-1"]},
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        other_created = await client.post(
            "/api/v1/sessions",
            json={"client_user_id": "anon-2", "title": "物理题"},
        )
        assert other_created.status_code == 200

        listed = await client.get("/api/v1/sessions", params={"client_user_id": "anon-1"})
        detail = await client.get(f"/api/v1/sessions/{session_id}")

    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["session_id"] == session_id
    assert listed.json()["items"][0]["title"] == "几何题"
    assert detail.status_code == 200
    assert detail.json()["session_id"] == session_id
    assert detail.json()["asset_ids"] == ["asset-1"]


@pytest.mark.asyncio
async def test_session_detail_returns_message_history_and_summary():
    app = create_app()
    session_service = InMemorySessionService()

    async def fake_session_service():
        return session_service

    app.dependency_overrides[get_session_service] = fake_session_service
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/sessions",
            json={"client_user_id": "anon-1", "title": "几何题", "asset_ids": ["asset-1"]},
        )
        session_id = created.json()["session_id"]
        await session_service.append_message(
            ChatMessageCreate(
                session_id=session_id,
                role="user",
                content="请直接解答",
                mode="direct",
                attachments=[{"asset_id": "asset-1"}],
            )
        )
        await session_service.append_message(
            ChatMessageCreate(
                session_id=session_id,
                role="assistant",
                content="答案是 42°",
                mode="direct",
                knowledge_points=["角平分线"],
                raw_metadata={"subject": "数学"},
            )
        )

        listed = await client.get("/api/v1/sessions", params={"client_user_id": "anon-1"})
        detail = await client.get(f"/api/v1/sessions/{session_id}")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["last_message"] == "答案是 42°"
    assert listed.json()["items"][0]["subject"] == "数学"
    assert listed.json()["items"][0]["knowledge_points"] == ["角平分线"]

    body = detail.json()
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["attachments"] == [{"asset_id": "asset-1"}]
    assert body["messages"][1]["role"] == "assistant"
    assert body["messages"][1]["knowledge_points"] == ["角平分线"]


@pytest.mark.asyncio
async def test_session_context_update_always_overwrites():
    service = InMemorySessionService()
    session = await service.create_session(
        request=SessionCreateRequest(
            client_user_id="anon-1",
            title="几何题",
        )
    )

    await service.update_context(
        session["session_id"],
        current_question="求角 A",
        current_diagram="AB 与 CD 相交",
        current_knowledge={"points": ["对顶角"]},
        current_geometry={"version": "1.0", "given_relations": []},
    )

    detail = await service.get_session(session["session_id"])
    assert detail["current_question"] == "求角 A"
    assert detail["current_diagram"] == "AB 与 CD 相交"
    assert detail["current_knowledge"] == {"points": ["对顶角"]}
    assert detail["current_geometry"] == {"version": "1.0", "given_relations": []}

    await service.update_context(
        session["session_id"],
        current_question="新问题",
        current_diagram="新图",
        current_knowledge={"points": ["新知识点"]},
        current_geometry=None,
    )

    detail = await service.get_session(session["session_id"])
    assert detail["current_question"] == "新问题"
    assert detail["current_diagram"] == "新图"
    assert detail["current_knowledge"] == {"points": ["新知识点"]}
    assert detail["current_geometry"] is None
