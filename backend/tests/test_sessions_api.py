# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_sessions_can_be_created_listed_and_read():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/sessions",
            json={"client_user_id": "anon-1", "title": "几何题", "asset_ids": ["asset-1"]},
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        listed = await client.get("/api/v1/sessions", params={"client_user_id": "anon-1"})
        detail = await client.get(f"/api/v1/sessions/{session_id}")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["session_id"] == session_id
    assert listed.json()["items"][0]["title"] == "几何题"
    assert detail.status_code == 200
    assert detail.json()["session_id"] == session_id
    assert detail.json()["asset_ids"] == ["asset-1"]
