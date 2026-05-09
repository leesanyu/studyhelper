# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    anonymous_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))

    sessions = relationship("ChatSession", back_populates="user")
    assets = relationship("Asset", back_populates="user")
