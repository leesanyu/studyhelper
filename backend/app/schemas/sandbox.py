# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pydantic import BaseModel, Field


class PythonFigureRequest(BaseModel):
    code: str = Field(min_length=1, max_length=6000)
    session_id: str | None = None
    message_id: str | None = None
    width: int = Field(default=800, ge=240, le=2000)
    height: int = Field(default=600, ge=180, le=2000)


class PythonFigureResponse(BaseModel):
    asset_id: str
    image_url: str
    mime_type: str = "image/png"
    width: int
    height: int
    elapsed_ms: int
    stderr: str = ""
