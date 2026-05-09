# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    asset_id: str
    preview_url: str
    dify_file_id: str | None
    mime_type: str
    size: int
