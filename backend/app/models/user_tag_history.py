# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class UserTagHistory(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_tags_history"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    subject: Mapped[str] = mapped_column(String(128), index=True)
    knowledge_point: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(32), default="dify")
