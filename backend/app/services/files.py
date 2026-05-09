# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import StudyHelperError
from app.services.assets import AssetCreate, AssetRepository
from app.services.storage import AssetStorage


class DifyUploadClient(Protocol):
    async def upload_file(
        self, *, filename: str, content: bytes, mime_type: str, user: str
    ) -> dict:
        ...


class FileService(Protocol):
    async def upload_image(self, *, file: UploadFile, client_user_id: str) -> dict:
        ...


class ImageUploadService:
    allowed_extensions = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
    }
    image_format_to_mime = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }

    def __init__(
        self,
        *,
        dify_client: DifyUploadClient,
        asset_repository: AssetRepository,
        storage: AssetStorage,
        max_bytes: int = 20 * 1024 * 1024,
        max_image_dimension: int = 1600,
        jpeg_quality: int = 85,
        webp_quality: int = 85,
    ) -> None:
        self._dify_client = dify_client
        self._asset_repository = asset_repository
        self._storage = storage
        self.max_bytes = max_bytes
        self.max_image_dimension = max_image_dimension
        self.jpeg_quality = jpeg_quality
        self.webp_quality = webp_quality

    async def upload_image(self, *, file: UploadFile, client_user_id: str) -> dict:
        mime_type = file.content_type or "application/octet-stream"
        if mime_type not in self.allowed_extensions:
            raise StudyHelperError("Only png, jpeg and webp images are supported", 400, "invalid_file_type")
        content = await file.read()
        if len(content) > self.max_bytes:
            raise StudyHelperError("Image is too large", 413, "file_too_large")
        extension = self._validate_extension(file.filename, mime_type)
        width, height = self._validate_image_header(content, mime_type)
        processed_content, width, height = self._resize_if_needed(
            content=content,
            mime_type=mime_type,
            width=width,
            height=height,
        )

        dify_response = await self._dify_client.upload_file(
            filename=file.filename or f"question{extension}",
            content=processed_content,
            mime_type=mime_type,
            user=client_user_id,
        )
        dify_file_id = dify_response.get("id") or dify_response.get("file_id")

        asset_id = str(uuid4())
        stored = await self._storage.save(
            asset_id=asset_id, content=processed_content, extension=extension
        )
        await self._asset_repository.create_asset(
            AssetCreate(
                asset_id=asset_id,
                asset_type="question_image",
                storage_backend=stored["storage_backend"],
                object_key=stored["object_key"],
                url=stored["url"],
                dify_file_id=dify_file_id,
                filename=file.filename,
                mime_type=mime_type,
                size_bytes=len(processed_content),
                width=width,
                height=height,
                metadata={"client_user_id": client_user_id},
            )
        )

        return {
            "asset_id": asset_id,
            "preview_url": stored["url"],
            "dify_file_id": dify_file_id,
            "mime_type": mime_type,
            "size": len(processed_content),
        }

    def _validate_extension(self, filename: str | None, mime_type: str) -> str:
        extension = Path(filename or "").suffix.lower()
        if extension not in self.allowed_extensions[mime_type]:
            raise StudyHelperError(
                "Image extension does not match content type",
                400,
                "invalid_file_extension",
            )
        return extension

    def _validate_image_header(self, content: bytes, mime_type: str) -> tuple[int, int]:
        try:
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                detected_mime = self.image_format_to_mime.get(image.format or "")
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise StudyHelperError("Uploaded file is not a valid image", 400, "invalid_image") from exc

        if detected_mime != mime_type:
            raise StudyHelperError("Image header does not match content type", 400, "invalid_image")
        return width, height

    def _resize_if_needed(
        self,
        *,
        content: bytes,
        mime_type: str,
        width: int,
        height: int,
    ) -> tuple[bytes, int, int]:
        longest_edge = max(width, height)
        if longest_edge <= self.max_image_dimension:
            return content, width, height

        scale = self.max_image_dimension / longest_edge
        target_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        try:
            with Image.open(BytesIO(content)) as image:
                resized = image.resize(target_size, Image.Resampling.LANCZOS)
                output = BytesIO()
                self._save_image(resized, output, mime_type)
        except (OSError, UnidentifiedImageError) as exc:
            raise StudyHelperError("Failed to resize uploaded image", 400, "invalid_image") from exc

        return output.getvalue(), target_size[0], target_size[1]

    def _save_image(self, image: Image.Image, output: BytesIO, mime_type: str) -> None:
        if mime_type == "image/jpeg":
            image.convert("RGB").save(output, format="JPEG", quality=self.jpeg_quality, optimize=True)
        elif mime_type == "image/webp":
            image.save(output, format="WEBP", quality=self.webp_quality, method=6)
        else:
            image.save(output, format="PNG", optimize=True)
