# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pathlib import Path

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat import ChatService, DifyChatService
from app.core.config import get_settings
from app.db.session import get_db_session
from app.services.assets import SqlAlchemyAssetRepository
from app.services.dify import DifyClient
from app.services.files import FileService, ImageUploadService
from app.services.messages import SqlAlchemyChatMessageRepository
from app.services.sandbox import InMemoryPythonFigureSandboxService, PythonFigureSandboxService
from app.services.sessions import InMemorySessionService, SessionService, SqlAlchemyChatSessionRepository
from app.services.storage import LocalAssetStorage

_sandbox_service = InMemoryPythonFigureSandboxService()
_session_service = InMemorySessionService()


async def get_chat_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> ChatService:
    settings = get_settings()
    return DifyChatService(
        dify_client=DifyClient(settings.dify_api_url, settings.dify_api_key),
        asset_repository=SqlAlchemyAssetRepository(db_session),
        session_repository=SqlAlchemyChatSessionRepository(db_session),
        message_repository=SqlAlchemyChatMessageRepository(db_session),
    )


async def get_file_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> FileService:
    settings = get_settings()
    return ImageUploadService(
        dify_client=DifyClient(settings.dify_api_url, settings.dify_api_key),
        asset_repository=SqlAlchemyAssetRepository(db_session),
        storage=LocalAssetStorage(
            root_dir=Path(settings.asset_storage_path),
            base_url=settings.asset_base_url,
        ),
        max_image_dimension=settings.upload_max_image_dimension,
        jpeg_quality=settings.upload_jpeg_quality,
        webp_quality=settings.upload_webp_quality,
    )


async def get_sandbox_service() -> PythonFigureSandboxService:
    return _sandbox_service


async def get_session_service() -> SessionService:
    return _session_service
