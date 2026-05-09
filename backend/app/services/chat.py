# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from collections.abc import AsyncIterator
from typing import Protocol

from app.core.exceptions import StudyHelperError
from app.schemas.chat import ChatCompletionRequest
from app.services.assets import AssetRepository
from app.services.messages import ChatMessageCreate, ChatMessageRepository
from app.services.sessions import ChatSessionRepository


class DifyChatClient(Protocol):
    async def stream_chat(
        self,
        query: str,
        user: str,
        conversation_id: str | None,
        files: list[dict] | None = None,
        inputs: dict | None = None,
    ) -> AsyncIterator[dict]:
        ...


class ChatService(Protocol):
    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncIterator[dict]:
        ...


class InMemoryChatService:
    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncIterator[dict]:
        session_id = request.session_id or "local-session"
        yield {"event": "message_start", "data": {"session_id": session_id}}
        yield {"event": "delta", "data": {"text": request.message}}
        yield {"event": "message_end", "data": {"session_id": session_id, "message_id": "local-message"}}


class DifyChatService:
    def __init__(
        self,
        *,
        dify_client: DifyChatClient,
        asset_repository: AssetRepository,
        session_repository: ChatSessionRepository | None = None,
        message_repository: ChatMessageRepository | None = None,
    ) -> None:
        self._dify_client = dify_client
        self._asset_repository = asset_repository
        self._session_repository = session_repository
        self._message_repository = message_repository

    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncIterator[dict]:
        try:
            files = await self._build_dify_files(request.asset_ids)
            conversation_id = await self._get_conversation_id(request.session_id)
            await self._update_question_context(request)
        except StudyHelperError as exc:
            yield {"event": "error", "data": {"code": exc.code, "message": exc.message}}
            return

        await self._persist_user_message(request)
        assistant_chunks: list[str] = []
        message_end_data: dict = {}
        conversation_recorded = bool(conversation_id)
        async for event in self._dify_client.stream_chat(
            query=request.message,
            user=request.client_user_id,
            conversation_id=conversation_id,
            files=files,
            inputs={"mode": request.mode},
        ):
            data = dict(event.get("data") or {})
            if request.session_id:
                data.setdefault("session_id", request.session_id)
            event_name = event.get("event", "delta")
            if event_name == "message_start":
                conversation_recorded = await self._record_conversation_id(
                    session_id=request.session_id,
                    conversation_id=data.get("conversation_id"),
                    already_recorded=conversation_recorded,
                )
            elif event_name == "delta":
                assistant_chunks.append(str(data.get("text", "")))
            elif event_name == "message_end":
                message_end_data = data
                await self._persist_assistant_message(
                    request=request,
                    content="".join(assistant_chunks),
                    message_end_data=message_end_data,
                )
            yield {"event": event_name, "data": data}

    async def _record_conversation_id(
        self,
        *,
        session_id: str | None,
        conversation_id: str | None,
        already_recorded: bool,
    ) -> bool:
        if already_recorded or not session_id or not conversation_id or self._session_repository is None:
            return already_recorded
        await self._session_repository.update_dify_conversation_id(session_id, conversation_id)
        return True

    async def _get_conversation_id(self, session_id: str | None) -> str | None:
        if not session_id or self._session_repository is None:
            return None
        session = await self._session_repository.get_session(session_id)
        if not session:
            raise StudyHelperError(f"Session not found: {session_id}", 404, "session_not_found")
        return session.get("dify_conversation_id")

    async def _update_question_context(self, request: ChatCompletionRequest) -> None:
        if not request.session_id or self._session_repository is None:
            return
        await self._session_repository.update_context(
            request.session_id,
            mode=request.mode,
            current_question=request.current_question,
            current_diagram=request.current_diagram,
            current_knowledge=request.current_knowledge,
        )

    async def _persist_user_message(self, request: ChatCompletionRequest) -> None:
        if not request.session_id or self._message_repository is None:
            return
        await self._message_repository.create_message(
            ChatMessageCreate(
                session_id=request.session_id,
                role="user",
                content=request.message,
                mode=request.mode,
                attachments=[{"asset_id": asset_id} for asset_id in request.asset_ids],
                raw_metadata={"client_user_id": request.client_user_id},
            )
        )

    async def _persist_assistant_message(
        self,
        *,
        request: ChatCompletionRequest,
        content: str,
        message_end_data: dict,
    ) -> None:
        if not request.session_id or self._message_repository is None:
            return
        await self._message_repository.create_message(
            ChatMessageCreate(
                session_id=request.session_id,
                role="assistant",
                content=content,
                mode=request.mode,
                dify_message_id=message_end_data.get("dify_message_id"),
                knowledge_points=list(message_end_data.get("knowledge_points") or []),
                raw_metadata=message_end_data,
            )
        )

    async def _build_dify_files(self, asset_ids: list[str]) -> list[dict]:
        if not asset_ids:
            return []

        assets = await self._asset_repository.get_assets_by_ids(asset_ids)
        assets_by_id = {asset["asset_id"]: asset for asset in assets}
        files: list[dict] = []
        for asset_id in asset_ids:
            asset = assets_by_id.get(asset_id)
            if not asset:
                raise StudyHelperError(f"Asset not found: {asset_id}", 404, "asset_not_found")
            dify_file_id = asset.get("dify_file_id")
            if not dify_file_id:
                raise StudyHelperError(
                    f"Asset has no Dify file id: {asset_id}",
                    400,
                    "asset_missing_dify_file_id",
                )
            files.append(
                {
                    "type": self._dify_file_type(asset.get("mime_type")),
                    "transfer_method": "local_file",
                    "upload_file_id": dify_file_id,
                }
            )
        return files

    def _dify_file_type(self, mime_type: str | None) -> str:
        if mime_type and mime_type.startswith("image/"):
            return "image"
        return "custom"
