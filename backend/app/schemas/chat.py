# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pydantic import BaseModel, Field


class ChatCompletionRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1)
    mode: str = "guide"
    file_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    client_user_id: str = "anonymous"
