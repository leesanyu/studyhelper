# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class ChatSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    current_question: Mapped[str | None] = mapped_column(Text)
    current_diagram: Mapped[str | None] = mapped_column(Text)
    current_knowledge: Mapped[dict | None] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session")
    assets = relationship("Asset", back_populates="session")
