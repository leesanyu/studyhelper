# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    client_user_id: str = "anonymous"
    title: str | None = None
    asset_ids: list[str] = Field(default_factory=list)


class SessionSummary(BaseModel):
    session_id: str
    title: str | None
    status: str
    last_message: str | None = None
    subject: str | None = None
    knowledge_points: list[str] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    items: list[SessionSummary]


class SessionDetailResponse(SessionSummary):
    client_user_id: str
    asset_ids: list[str] = Field(default_factory=list)
    messages: list[dict] = Field(default_factory=list)
