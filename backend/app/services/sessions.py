# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from typing import Protocol
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_session import ChatSession
from app.schemas.sessions import SessionCreateRequest


class SessionService(Protocol):
    async def create_session(self, request: SessionCreateRequest) -> dict:
        ...

    async def list_sessions(self, client_user_id: str) -> list[dict]:
        ...

    async def get_session(self, session_id: str) -> dict | None:
        ...


class ChatSessionRepository(Protocol):
    async def get_session(self, session_id: str) -> dict | None:
        ...

    async def update_dify_conversation_id(self, session_id: str, conversation_id: str) -> None:
        ...


class InMemorySessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._order: list[str] = []

    async def create_session(self, request: SessionCreateRequest) -> dict:
        session_id = str(uuid4())
        session = {
            "session_id": session_id,
            "client_user_id": request.client_user_id,
            "title": request.title,
            "status": "active",
            "asset_ids": list(request.asset_ids),
            "messages": [],
            "last_message": None,
        }
        self._sessions[session_id] = session
        self._order.insert(0, session_id)
        return session

    async def list_sessions(self, client_user_id: str) -> list[dict]:
        return [
            self._sessions[session_id]
            for session_id in self._order
            if self._sessions[session_id]["client_user_id"] == client_user_id
        ]

    async def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)


class SqlAlchemyChatSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_session(self, session_id: str) -> dict | None:
        result = await self._session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "session_id": row.id,
            "client_user_id": row.user_id,
            "title": row.title,
            "status": row.status,
            "dify_conversation_id": row.dify_conversation_id,
            "current_question": row.current_question,
            "current_diagram": row.current_diagram,
            "current_knowledge": row.current_knowledge,
        }

    async def update_dify_conversation_id(self, session_id: str, conversation_id: str) -> None:
        await self._session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(dify_conversation_id=conversation_id)
        )
        await self._session.commit()
