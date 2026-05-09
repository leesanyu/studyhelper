# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import httpx
import pytest

from app.api.deps import get_file_service
from app.main import create_app

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeFileService:
    async def upload_image(self, *, file, client_user_id: str):
        content = await file.read()
        return {
            "asset_id": "asset-1",
            "preview_url": "/assets/question.png",
            "dify_file_id": "file-1",
            "mime_type": file.content_type,
            "size": len(content),
        }


async def fake_file_service():
    return FakeFileService()


@pytest.mark.asyncio
async def test_file_upload_returns_asset_and_dify_file_id():
    app = create_app()
    app.dependency_overrides[get_file_service] = fake_file_service
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/files/upload",
            data={"client_user_id": "anon-1"},
            files={"file": ("question.png", PNG_1X1, "image/png")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": "asset-1",
        "preview_url": "/assets/question.png",
        "dify_file_id": "file-1",
        "mime_type": "image/png",
        "size": len(PNG_1X1),
    }
