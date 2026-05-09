# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import logging

from fastapi import FastAPI
from starlette.requests import Request
from uuid import uuid4

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(title=app_settings.app_name, version=app_settings.app_version)
    app.state.settings = app_settings
    request_logger = logging.getLogger("studyhelper.request")

    register_exception_handlers(app)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            request_logger.exception(
                "request_id=%s method=%s path=%s status=500",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        request_logger.info(
            "request_id=%s method=%s path=%s status=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
        )
        return response

    app.include_router(api_router)

    return app


app = create_app()
