# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import logging

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_health_returns_service_status():
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "studyhelper-backend"
    assert "dependencies" in body


@pytest.mark.asyncio
async def test_api_v1_health_matches_root_health():
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_request_id_header_is_returned():
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-ID": "req-test-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-1"


@pytest.mark.asyncio
async def test_request_log_includes_request_id_method_path_and_status(caplog):
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    with caplog.at_level(logging.INFO, logger="studyhelper.request"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health", headers={"X-Request-ID": "req-log-1"})

    assert response.status_code == 200
    log_messages = [record.getMessage() for record in caplog.records]
    assert any(
        "request_id=req-log-1" in message
        and "method=GET" in message
        and "path=/health" in message
        and "status=200" in message
        for message in log_messages
    )
