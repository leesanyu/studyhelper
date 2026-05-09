# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from fastapi import APIRouter

from app.api.v1.routes import chat, files, health, sandbox, sessions

api_router = APIRouter()
api_router.include_router(chat.router)
api_router.include_router(files.router)
api_router.include_router(health.router)
api_router.include_router(sandbox.router)
api_router.include_router(sessions.router)
