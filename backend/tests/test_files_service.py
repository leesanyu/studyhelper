# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import pytest
from io import BytesIO
from PIL import Image

from app.core.exceptions import StudyHelperError
from app.services.assets import InMemoryAssetRepository
from app.services.files import ImageUploadService
from app.services.storage import LocalAssetStorage

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeDifyUploadClient:
    def __init__(self, response: dict | None = None, error: StudyHelperError | None = None) -> None:
        self.response = response or {"id": "dify-file-1"}
        self.error = error
        self.calls: list[dict] = []

    async def upload_file(self, *, filename: str, content: bytes, mime_type: str, user: str) -> dict:
        self.calls.append(
            {
                "filename": filename,
                "content": content,
                "mime_type": mime_type,
                "user": user,
            }
        )
        if self.error:
            raise self.error
        return self.response


class FailingStorage:
    async def save(self, *, asset_id: str, content: bytes, extension: str) -> dict:
        raise StudyHelperError("Storage failed", 500, "asset_storage_error")


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str) -> None:
        self.filename = filename
        self._content = content
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._content


def make_upload(filename: str, content: bytes, content_type: str) -> FakeUploadFile:
    return FakeUploadFile(filename=filename, content=content, content_type=content_type)


def make_jpeg(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(42, 120, 200))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def read_image_size(content: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(content)) as image:
        return image.size


@pytest.mark.asyncio
async def test_upload_image_saves_preview_and_records_asset(tmp_path):
    dify_client = FakeDifyUploadClient()
    repository = InMemoryAssetRepository()
    service = ImageUploadService(
        dify_client=dify_client,
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    response = await service.upload_image(
        file=make_upload("question.png", PNG_1X1, "image/png"),
        client_user_id="anon-1",
    )

    assert response["dify_file_id"] == "dify-file-1"
    assert response["mime_type"] == "image/png"
    assert response["size"] == len(PNG_1X1)
    assert response["preview_url"].startswith("/assets/uploads/")
    assert dify_client.calls[0]["user"] == "anon-1"
    assert dify_client.calls[0]["filename"] == "question.png"

    stored_asset = repository.assets[response["asset_id"]]
    assert stored_asset["asset_type"] == "question_image"
    assert stored_asset["dify_file_id"] == "dify-file-1"
    assert stored_asset["filename"] == "question.png"
    assert stored_asset["width"] == 1
    assert stored_asset["height"] == 1
    assert (tmp_path / stored_asset["object_key"]).exists()


@pytest.mark.asyncio
async def test_upload_image_resizes_large_image_before_dify_and_storage(tmp_path):
    original = make_jpeg(width=1600, height=1200)
    dify_client = FakeDifyUploadClient()
    repository = InMemoryAssetRepository()
    service = ImageUploadService(
        dify_client=dify_client,
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
        max_image_dimension=800,
    )

    response = await service.upload_image(
        file=make_upload("question.jpg", original, "image/jpeg"),
        client_user_id="anon-1",
    )

    stored_asset = repository.assets[response["asset_id"]]
    stored_content = (tmp_path / stored_asset["object_key"]).read_bytes()
    assert stored_asset["width"] == 800
    assert stored_asset["height"] == 600
    assert response["size"] == len(stored_content)
    assert read_image_size(dify_client.calls[0]["content"]) == (800, 600)
    assert read_image_size(stored_content) == (800, 600)


@pytest.mark.asyncio
async def test_upload_image_rejects_invalid_image_header(tmp_path):
    service = ImageUploadService(
        dify_client=FakeDifyUploadClient(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    with pytest.raises(StudyHelperError) as exc_info:
        await service.upload_image(
            file=make_upload("question.png", b"not a png", "image/png"),
            client_user_id="anon-1",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_image"


@pytest.mark.asyncio
async def test_upload_image_rejects_extension_mismatch(tmp_path):
    service = ImageUploadService(
        dify_client=FakeDifyUploadClient(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    with pytest.raises(StudyHelperError) as exc_info:
        await service.upload_image(
            file=make_upload("question.txt", PNG_1X1, "image/png"),
            client_user_id="anon-1",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_file_extension"


@pytest.mark.asyncio
async def test_upload_image_rejects_oversized_file(tmp_path):
    service = ImageUploadService(
        dify_client=FakeDifyUploadClient(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
        max_bytes=len(PNG_1X1) - 1,
    )

    with pytest.raises(StudyHelperError) as exc_info:
        await service.upload_image(
            file=make_upload("question.png", PNG_1X1, "image/png"),
            client_user_id="anon-1",
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "file_too_large"


@pytest.mark.asyncio
async def test_upload_image_does_not_record_asset_when_dify_upload_fails(tmp_path):
    repository = InMemoryAssetRepository()
    service = ImageUploadService(
        dify_client=FakeDifyUploadClient(
            error=StudyHelperError("Dify upload failed", 502, "dify_file_upload_error")
        ),
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    with pytest.raises(StudyHelperError) as exc_info:
        await service.upload_image(
            file=make_upload("question.png", PNG_1X1, "image/png"),
            client_user_id="anon-1",
        )

    assert exc_info.value.code == "dify_file_upload_error"
    assert repository.assets == {}
    assert not list(tmp_path.rglob("*"))


@pytest.mark.asyncio
async def test_upload_image_does_not_record_asset_when_storage_fails():
    repository = InMemoryAssetRepository()
    service = ImageUploadService(
        dify_client=FakeDifyUploadClient(),
        asset_repository=repository,
        storage=FailingStorage(),
    )

    with pytest.raises(StudyHelperError) as exc_info:
        await service.upload_image(
            file=make_upload("question.png", PNG_1X1, "image/png"),
            client_user_id="anon-1",
        )

    assert exc_info.value.code == "asset_storage_error"
    assert repository.assets == {}
