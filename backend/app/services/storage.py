# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pathlib import Path
from typing import Protocol

from app.core.exceptions import StudyHelperError


class AssetStorage(Protocol):
    async def save(
        self, *, asset_id: str, content: bytes, extension: str, prefix: str = "uploads"
    ) -> dict:
        ...


class LocalAssetStorage:
    def __init__(self, root_dir: str | Path, base_url: str = "/assets") -> None:
        self._root_dir = Path(root_dir)
        self._base_url = base_url.rstrip("/")

    async def save(
        self, *, asset_id: str, content: bytes, extension: str, prefix: str = "uploads"
    ) -> dict:
        safe_prefix = prefix.strip("/ ") or "uploads"
        object_key = f"{safe_prefix}/{asset_id}{extension}"
        output_path = self._root_dir / object_key
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
        except OSError as exc:
            raise StudyHelperError("Failed to store uploaded image", 500, "asset_storage_error") from exc

        return {
            "storage_backend": "local",
            "object_key": object_key,
            "url": f"{self._base_url}/{object_key}",
        }
