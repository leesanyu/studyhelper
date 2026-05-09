# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json
from collections.abc import AsyncIterator

import httpx

from app.core.exceptions import StudyHelperError


class DifyClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def stream_chat(
        self,
        query: str,
        user: str,
        conversation_id: str | None,
        files: list[dict] | None = None,
        inputs: dict | None = None,
    ) -> AsyncIterator[dict]:
        payload = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": "streaming",
            "user": user,
            "files": files or [],
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        seen_start = False
        async with self._client.stream(
            "POST",
            f"{self.api_url}/v1/chat-messages",
            headers=self.headers,
            json=payload,
        ) as response:
            if response.status_code >= 400:
                raise StudyHelperError(
                    f"Dify chat request failed with status {response.status_code}",
                    status_code=502,
                    code="dify_chat_error",
                )

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line.removeprefix("data: ").strip()
                if not raw or raw == "[DONE]":
                    continue
                event = json.loads(raw)
                dify_event = event.get("event")
                conversation = event.get("conversation_id")
                message = event.get("message_id")

                if dify_event == "message":
                    if not seen_start:
                        seen_start = True
                        yield {
                            "event": "message_start",
                            "data": {
                                "conversation_id": conversation,
                                "dify_message_id": message,
                            },
                        }
                    yield {"event": "delta", "data": {"text": event.get("answer", "")}}
                elif dify_event in {"message_end", "workflow_finished"}:
                    if not seen_start:
                        seen_start = True
                        yield {
                            "event": "message_start",
                            "data": {
                                "conversation_id": conversation,
                                "dify_message_id": message,
                            },
                        }
                    yield {
                        "event": "message_end",
                        "data": {
                            "conversation_id": conversation,
                            "dify_message_id": message,
                        },
                    }
                elif dify_event == "error":
                    yield {
                        "event": "error",
                        "data": {
                            "code": event.get("code", "dify_error"),
                            "message": event.get("message", "Dify stream error"),
                        },
                    }

    async def upload_file(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str,
        user: str,
    ) -> dict:
        files = {"file": (filename, content, mime_type)}
        data = {"user": user}
        response = await self._client.post(
            f"{self.api_url}/v1/files/upload",
            headers=self.headers,
            files=files,
            data=data,
        )
        if response.status_code >= 400:
            raise StudyHelperError(
                f"Dify file upload failed with status {response.status_code}",
                status_code=502,
                code="dify_file_upload_error",
            )
        return response.json()
