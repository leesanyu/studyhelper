# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from dataclasses import asdict, dataclass, field
from typing import Protocol

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
    dify_message_id: str | None = None
    attachments: list = field(default_factory=list)
    knowledge_points: list = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


class ChatMessageRepository(Protocol):
    async def create_message(self, message: ChatMessageCreate) -> dict:
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
                    "source": "dify",
                }
            )


class SqlAlchemyChatMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_message(self, message: ChatMessageCreate) -> dict:
        row = ChatMessage(
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            mode=message.mode,
            dify_message_id=message.dify_message_id,
            attachments=message.attachments,
            knowledge_points=message.knowledge_points,
            raw_metadata=message.raw_metadata,
        )
        self._session.add(row)
        await self._create_tag_history(row=row, message=message)
        await self._session.commit()
        return asdict(message)

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
                    source="dify",
                )
            )
