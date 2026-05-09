# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from sqlalchemy import ForeignKey, JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class Asset(IdMixin, TimestampMixin, Base):
    __tablename__ = "assets"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    storage_backend: Mapped[str] = mapped_column(String(32), default="local")
    object_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(1024))
    dify_file_id: Mapped[str | None] = mapped_column(String(128), index=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict)

    user = relationship("User", back_populates="assets")
    session = relationship("ChatSession", back_populates="assets")
    message = relationship("ChatMessage", back_populates="assets")
