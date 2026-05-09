# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


def _health_payload(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "dependencies": {
            "database": "not_checked",
            "redis": "not_checked",
            "minio": "not_checked",
        },
    }


@router.get("/health")
async def root_health(request: Request) -> dict:
    return _health_payload(request)


@router.get("/api/v1/health")
async def api_health(request: Request) -> dict:
    return _health_payload(request)
