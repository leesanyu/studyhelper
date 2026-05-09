# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from fastapi import APIRouter, Depends

from app.api.deps import get_sandbox_service
from app.schemas.sandbox import PythonFigureRequest, PythonFigureResponse
from app.services.sandbox import PythonFigureSandboxService

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])


@router.post("/python-figure", response_model=PythonFigureResponse)
async def render_python_figure(
    request: PythonFigureRequest,
    sandbox_service: PythonFigureSandboxService = Depends(get_sandbox_service),
) -> dict:
    return await sandbox_service.render_figure(request)
