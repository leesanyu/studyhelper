# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.api.deps import get_chat_service
from app.schemas.chat import ChatCompletionRequest
from app.services.chat import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def encode_sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class SimpleSSEStreamingResponse(Response):
    media_type = "text/event-stream"

    def __init__(self, body_iterator: AsyncIterator[str], status_code: int = 200) -> None:
        self.body_iterator = body_iterator
        super().__init__(content=b"", status_code=status_code, media_type=self.media_type)
        self.raw_headers = [
            header for header in self.raw_headers if header[0].lower() != b"content-length"
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for chunk in self.body_iterator:
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk.encode("utf-8"),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b"", "more_body": False})


@router.post("/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> SimpleSSEStreamingResponse:
    async def stream() -> AsyncIterator[str]:
        async for event in chat_service.stream_chat(request):
            yield encode_sse(event)

    return SimpleSSEStreamingResponse(stream())
