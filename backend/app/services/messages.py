# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from dataclasses import asdict, dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.user_tag_history import UserTagHistory


@dataclass(frozen=True)
class ChatMessageCreate:
    session_id: str
    role: str
    content: str
    mode: str | None = None
    attachments: list = field(default_factory=list)
    knowledge_points: list = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


class ChatMessageRepository(Protocol):
    async def create_message(self, message: ChatMessageCreate) -> dict:
        ...

    async def rollback(self) -> None:
        ...


class InMemoryChatMessageRepository:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.tags: list[dict] = []

    async def create_message(self, message: ChatMessageCreate) -> dict:
        payload = asdict(message)
        self.messages.append(payload)
        self._record_tags(message)
        return payload

    async def rollback(self) -> None:
        return None

    def _record_tags(self, message: ChatMessageCreate) -> None:
        subject = message.raw_metadata.get("subject")
        if not subject:
            return
        for point in message.knowledge_points:
            self.tags.append(
                {
                    "session_id": message.session_id,
                    "subject": subject,
                    "knowledge_point": point,
                    "source": "agent",
                }
            )


class SqlAlchemyChatMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return [
            {
                "role": row.role,
                "content": row.content,
                "mode": row.mode,
                "attachments": row.attachments or [],
                "knowledge_points": row.knowledge_points or [],
                "raw_metadata": row.raw_metadata or {},
            }
            for row in rows
        ]

    async def create_message(self, message: ChatMessageCreate) -> dict:
        row = ChatMessage(
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            mode=message.mode,
            attachments=message.attachments,
            knowledge_points=message.knowledge_points,
            raw_metadata=message.raw_metadata,
        )
        self._session.add(row)
        await self._session.flush()
        await self._create_tag_history(row=row, message=message)
        await self._session.commit()
        payload = asdict(message)
        payload["message_id"] = row.id
        return payload

    async def _create_tag_history(self, *, row: ChatMessage, message: ChatMessageCreate) -> None:
        subject = message.raw_metadata.get("subject")
        if not subject or not message.knowledge_points:
            return
        chat_session = await self._session.get(ChatSession, message.session_id)
        if chat_session is None:
            return
        for point in message.knowledge_points:
            self._session.add(
                UserTagHistory(
                    user_id=chat_session.user_id,
                    session_id=message.session_id,
                    message_id=row.id,
                    subject=subject,
                    knowledge_point=point,
                    source="agent",
                )
            )

    async def rollback(self) -> None:
        await self._session.rollback()
