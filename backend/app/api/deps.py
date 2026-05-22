# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pathlib import Path

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm_client import LLMClient
from app.agent.service import AgentService
from app.core.config import get_settings
from app.db.session import get_db_session
from app.services.assets import SqlAlchemyAssetRepository
from app.services.chat import AgentChatService, ChatService
from app.services.files import FileService, ImageUploadService
from app.services.messages import SqlAlchemyChatMessageRepository
from app.services.sandbox import DockerPythonFigureSandboxService, PythonFigureSandboxService
from app.services.sessions import SessionService, SqlAlchemyChatSessionRepository, SqlAlchemySessionService
from app.services.storage import LocalAssetStorage


async def get_chat_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> ChatService:
    settings = get_settings()
    llm_client = LLMClient(settings)
    agent_service = AgentService(
        llm_client=llm_client,
        asset_repository=SqlAlchemyAssetRepository(db_session),
        session_repository=SqlAlchemyChatSessionRepository(db_session),
        message_repository=SqlAlchemyChatMessageRepository(db_session),
        sandbox_service=DockerPythonFigureSandboxService(
            settings=settings,
            asset_repository=SqlAlchemyAssetRepository(db_session),
            storage=LocalAssetStorage(
                root_dir=Path(settings.asset_storage_path),
                base_url=settings.asset_base_url,
            ),
        ),
        settings=settings,
    )
    return AgentChatService(agent_service=agent_service)


async def get_file_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> FileService:
    settings = get_settings()
    return ImageUploadService(
        asset_repository=SqlAlchemyAssetRepository(db_session),
        storage=LocalAssetStorage(
            root_dir=Path(settings.asset_storage_path),
            base_url=settings.asset_base_url,
        ),
        max_image_dimension=settings.upload_max_image_dimension,
        jpeg_quality=settings.upload_jpeg_quality,
        webp_quality=settings.upload_webp_quality,
    )


async def get_sandbox_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> PythonFigureSandboxService:
    settings = get_settings()
    return DockerPythonFigureSandboxService(
        settings=settings,
        asset_repository=SqlAlchemyAssetRepository(db_session),
        storage=LocalAssetStorage(
            root_dir=Path(settings.asset_storage_path),
            base_url=settings.asset_base_url,
        ),
    )


async def get_session_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> SessionService:
    return SqlAlchemySessionService(db_session)