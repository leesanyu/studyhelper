# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import logging
import os

# 配置应用日志级别（含时间戳）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# uvicorn 访问日志也使用时间戳格式
for _logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _uv_logger = logging.getLogger(_logger_name)
    _uv_logger.handlers.clear()
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _uv_logger.addHandler(_handler)
    _uv_logger.propagate = False

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from uuid import uuid4

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(title=app_settings.app_name, version=app_settings.app_version)
    app.state.settings = app_settings
    request_logger = logging.getLogger("studyhelper.request")

    # CORS：仅在配置了 allow_origins 时启用（开发环境），生产环境由 Nginx 同源代理
    if app_settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    # 注意：不使用 @app.middleware("http")，因为 BaseHTTPMiddleware 与 StreamingResponse 不兼容。
    # request_id 通过 ASGI middleware 实现，不缓冲 response body。
    from starlette.types import ASGIApp, Receive, Scope, Send

    class RequestIdMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            request_id = None
            for header_name, header_value in scope.get("headers", []):
                if header_name == b"x-request-id":
                    request_id = header_value.decode()
                    break
            if not request_id:
                request_id = str(uuid4())

            scope.setdefault("state", {})["request_id"] = request_id

            async def send_with_request_id(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", request_id.encode()))
                    message = {**message, "headers": headers}
                    request_logger.info(
                        "request_id=%s method=%s path=%s status=%s",
                        request_id,
                        scope.get("method", ""),
                        scope.get("path", ""),
                        message.get("status", ""),
                    )
                await send(message)

            await self.app(scope, receive, send_with_request_id)

    app.add_middleware(RequestIdMiddleware)

    app.include_router(api_router)

    # 静态文件服务：上传图片和沙箱生成图片的访问路径
    os.makedirs(app_settings.asset_storage_path, exist_ok=True)
    app.mount(
        app_settings.asset_base_url,
        StaticFiles(directory=app_settings.asset_storage_path),
        name="assets",
    )

    return app


app = create_app()
