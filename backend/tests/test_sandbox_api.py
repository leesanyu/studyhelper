# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_python_figure_sandbox_returns_generated_asset():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sandbox/python-figure",
            json={
                "code": "import matplotlib.pyplot as plt\nplt.plot([0, 1], [0, 1])",
                "session_id": "session-1",
                "width": 640,
                "height": 480,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"]
    assert body["image_url"].startswith("/assets/")
    assert body["mime_type"] == "image/png"
    assert body["width"] == 640
    assert body["height"] == 480
    assert body["elapsed_ms"] >= 0
    assert "stderr" in body


@pytest.mark.asyncio
async def test_python_figure_sandbox_rejects_dangerous_code():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sandbox/python-figure",
            json={"code": "import os\nos.listdir('/')"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "sandbox_rejected"
