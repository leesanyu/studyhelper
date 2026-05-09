# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from dataclasses import asdict, dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage


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

    async def create_message(self, message: ChatMessageCreate) -> dict:
        payload = asdict(message)
        self.messages.append(payload)
        return payload


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
        await self._session.commit()
        return asdict(message)
