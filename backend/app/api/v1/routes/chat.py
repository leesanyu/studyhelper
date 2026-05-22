# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.api.deps import get_chat_service
from app.schemas.chat import ChatCompletionRequest
from app.services.chat import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def encode_sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        async for event in chat_service.stream_chat(request):
            yield encode_sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
