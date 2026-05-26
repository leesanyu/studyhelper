# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from dataclasses import asdict, dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset


@dataclass(frozen=True)
class AssetCreate:
    asset_id: str
    asset_type: str
    storage_backend: str
    object_key: str
    url: str
    filename: str | None
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    user_id: str | None = None
    session_id: str | None = None
    message_id: str | None = None
    metadata: dict = field(default_factory=dict)


class AssetRepository(Protocol):
    async def create_asset(self, asset: AssetCreate) -> dict:
        ...

    async def get_assets_by_ids(self, asset_ids: list[str]) -> list[dict]:
        ...

    async def rollback(self) -> None:
        ...


class InMemoryAssetRepository:
    def __init__(self) -> None:
        self.assets: dict[str, dict] = {}

    async def create_asset(self, asset: AssetCreate) -> dict:
        payload = asdict(asset)
        self.assets[asset.asset_id] = payload
        return payload

    async def get_assets_by_ids(self, asset_ids: list[str]) -> list[dict]:
        return [self.assets[asset_id] for asset_id in asset_ids if asset_id in self.assets]

    async def rollback(self) -> None:
        return None


class SqlAlchemyAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_asset(self, asset: AssetCreate) -> dict:
        row = Asset(
            id=asset.asset_id,
            user_id=asset.user_id,
            session_id=asset.session_id,
            message_id=asset.message_id,
            asset_type=asset.asset_type,
            storage_backend=asset.storage_backend,
            object_key=asset.object_key,
            url=asset.url,
            filename=asset.filename,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            width=asset.width,
            height=asset.height,
            metadata_json=asset.metadata,
        )
        self._session.add(row)
        await self._session.commit()
        return asdict(asset)

    async def get_assets_by_ids(self, asset_ids: list[str]) -> list[dict]:
        if not asset_ids:
            return []
        result = await self._session.execute(select(Asset).where(Asset.id.in_(asset_ids)))
        rows = result.scalars().all()
        rows_by_id = {row.id: row for row in rows}
        return [
            {
                "asset_id": row.id,
                "asset_type": row.asset_type,
                "storage_backend": row.storage_backend,
                "object_key": row.object_key,
                "url": row.url,
                "filename": row.filename,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "width": row.width,
                "height": row.height,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "message_id": row.message_id,
                "metadata": row.metadata_json or {},
            }
            for asset_id in asset_ids
            if (row := rows_by_id.get(asset_id)) is not None
        ]

    async def rollback(self) -> None:
        await self._session.rollback()
