# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_session_service
from app.schemas.sessions import (
    SessionCreateRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
)
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("", response_model=SessionDetailResponse)
async def create_session(
    request: SessionCreateRequest,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    return await session_service.create_session(request)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    client_user_id: str = Query("anonymous"),
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    sessions = await session_service.list_sessions(client_user_id)
    return {"items": [SessionSummary(**session).model_dump() for session in sessions]}


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
