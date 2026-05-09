# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_file_service
from app.schemas.files import FileUploadResponse
from app.services.files import FileService

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    client_user_id: str = Form("anonymous"),
    file_service: FileService = Depends(get_file_service),
) -> dict:
    return await file_service.upload_image(file=file, client_user_id=client_user_id)
