# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from typing import Protocol
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.user import User
from app.services.messages import ChatMessageCreate
from app.schemas.sessions import SessionCreateRequest

_UNSET = object()


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

    async def update_context(
        self,
        session_id: str,
        *,
        current_question: str | None | object = _UNSET,
        current_diagram: str | None | object = _UNSET,
        current_knowledge: dict | None | object = _UNSET,
        current_geometry: dict | None | object = _UNSET,
    ) -> None:
        ...

    async def rollback(self) -> None:
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
            "subject": None,
            "knowledge_points": [],
            "current_question": None,
            "current_diagram": None,
            "current_knowledge": None,
            "current_geometry": None,
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

    async def append_message(self, message: ChatMessageCreate) -> dict:
        session = self._sessions[message.session_id]
        payload = {
            "role": message.role,
            "content": message.content,
            "mode": message.mode,
            "attachments": list(message.attachments),
            "knowledge_points": list(message.knowledge_points),
            "raw_metadata": dict(message.raw_metadata),
        }
        session["messages"].append(payload)
        session["last_message"] = message.content
        if subject := message.raw_metadata.get("subject"):
            session["subject"] = subject
        for point in message.knowledge_points:
            if point not in session["knowledge_points"]:
                session["knowledge_points"].append(point)
        self._touch_session(message.session_id)
        return payload

    def _touch_session(self, session_id: str) -> None:
        if session_id in self._order:
            self._order.remove(session_id)
        self._order.insert(0, session_id)

    async def update_context(
        self,
        session_id: str,
        *,
        current_question: str | None | object = _UNSET,
        current_diagram: str | None | object = _UNSET,
        current_knowledge: dict | None | object = _UNSET,
        current_geometry: dict | None | object = _UNSET,
    ) -> None:
        session = self._sessions[session_id]
        if current_question is not _UNSET:
            session["current_question"] = current_question
        if current_diagram is not _UNSET:
            session["current_diagram"] = current_diagram
        if current_knowledge is not _UNSET:
            session["current_knowledge"] = current_knowledge
        if current_geometry is not _UNSET:
            session["current_geometry"] = current_geometry
        self._touch_session(session_id)

    async def rollback(self) -> None:
        return None


class SqlAlchemySessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(self, request: SessionCreateRequest) -> dict:
        user = await self._get_or_create_user(request.client_user_id)
        row = ChatSession(
            user_id=user.id,
            title=request.title,
            status="active",
        )
        self._session.add(row)
        await self._session.flush()
        for asset_id in request.asset_ids:
            await self._session.execute(
                update(Asset).where(Asset.id == asset_id).values(session_id=row.id)
            )
        await self._session.commit()
        return {
            "session_id": row.id,
            "client_user_id": request.client_user_id,
            "title": row.title,
            "status": row.status,
            "asset_ids": list(request.asset_ids),
            "messages": [],
            "last_message": None,
            "subject": None,
            "knowledge_points": [],
            "current_question": row.current_question,
            "current_diagram": row.current_diagram,
            "current_knowledge": row.current_knowledge,
            "current_geometry": row.current_geometry,
        }

    async def list_sessions(self, client_user_id: str) -> list[dict]:
        user_result = await self._session.execute(
            select(User).where(User.anonymous_id == client_user_id)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            return []
        result = await self._session.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id, ChatSession.deleted_at.is_(None))
            .order_by(ChatSession.updated_at.desc())
        )
        sessions = result.scalars().all()
        return [await self._build_summary(session, client_user_id) for session in sessions]

    async def get_session(self, session_id: str) -> dict | None:
        result = await self._session.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        user = await self._session.get(User, session.user_id)
        summary = await self._build_summary(session, user.anonymous_id if user else "anonymous")
        messages = await self._load_messages(session_id)
        asset_ids = await self._load_asset_ids(session_id)
        return {
            **summary,
            "client_user_id": user.anonymous_id if user else "anonymous",
            "asset_ids": asset_ids,
            "messages": messages,
            "current_question": session.current_question,
            "current_diagram": session.current_diagram,
            "current_knowledge": session.current_knowledge,
            "current_geometry": session.current_geometry,
        }

    async def _get_or_create_user(self, client_user_id: str) -> User:
        result = await self._session.execute(select(User).where(User.anonymous_id == client_user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            return user
        user = User(anonymous_id=client_user_id, display_name="Anonymous")
        self._session.add(user)
        await self._session.flush()
        return user

    async def _build_summary(self, session: ChatSession, client_user_id: str) -> dict:
        messages = await self._load_messages(session.id)
        last_message = messages[-1]["content"] if messages else None
        subject = None
        knowledge_points: list[str] = []
        for message in messages:
            if message["raw_metadata"].get("subject"):
                subject = message["raw_metadata"]["subject"]
            for point in message["knowledge_points"]:
                if point not in knowledge_points:
                    knowledge_points.append(point)
        return {
            "session_id": session.id,
            "client_user_id": client_user_id,
            "title": session.title,
            "status": session.status,
            "last_message": last_message,
            "subject": subject,
            "knowledge_points": knowledge_points,
        }

    async def _load_messages(self, session_id: str) -> list[dict]:
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        )
        return [
            {
                "role": row.role,
                "content": row.content,
                "mode": row.mode,
                "attachments": row.attachments or [],
                "knowledge_points": row.knowledge_points or [],
                "raw_metadata": row.raw_metadata or {},
            }
            for row in result.scalars().all()
        ]

    async def _load_asset_ids(self, session_id: str) -> list[str]:
        result = await self._session.execute(select(Asset.id).where(Asset.session_id == session_id))
        return list(result.scalars().all())

    async def update_context(
        self,
        session_id: str,
        *,
        current_question: str | None | object = _UNSET,
        current_diagram: str | None | object = _UNSET,
        current_knowledge: dict | None | object = _UNSET,
        current_geometry: dict | None | object = _UNSET,
    ) -> None:
        values = _context_values(
            current_question=current_question,
            current_diagram=current_diagram,
            current_knowledge=current_knowledge,
            current_geometry=current_geometry,
        )
        if not values:
            return
        await self._session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(**values)
        )
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


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
            "current_question": row.current_question,
            "current_diagram": row.current_diagram,
            "current_knowledge": row.current_knowledge,
            "current_geometry": row.current_geometry,
        }

    async def update_context(
        self,
        session_id: str,
        *,
        current_question: str | None | object = _UNSET,
        current_diagram: str | None | object = _UNSET,
        current_knowledge: dict | None | object = _UNSET,
        current_geometry: dict | None | object = _UNSET,
    ) -> None:
        values = _context_values(
            current_question=current_question,
            current_diagram=current_diagram,
            current_knowledge=current_knowledge,
            current_geometry=current_geometry,
        )
        if not values:
            return
        await self._session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(**values)
        )
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def _context_values(
    *,
    current_question: str | None | object = _UNSET,
    current_diagram: str | None | object = _UNSET,
    current_knowledge: dict | None | object = _UNSET,
    current_geometry: dict | None | object = _UNSET,
) -> dict:
    values = {}
    if current_question is not _UNSET:
        values["current_question"] = current_question
    if current_diagram is not _UNSET:
        values["current_diagram"] = current_diagram
    if current_knowledge is not _UNSET:
        values["current_knowledge"] = current_knowledge
    if current_geometry is not _UNSET:
        values["current_geometry"] = current_geometry
    return values
