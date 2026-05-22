# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class ChatMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(String(32))
    attachments: Mapped[list | None] = mapped_column(JSON, default=list)
    knowledge_points: Mapped[list | None] = mapped_column(JSON, default=list)
    raw_metadata: Mapped[dict | None] = mapped_column(JSON, default=dict)

    session = relationship("ChatSession", back_populates="messages")
    assets = relationship("Asset", back_populates="message")
