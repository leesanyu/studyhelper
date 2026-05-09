# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "studyhelper-backend"
    app_version: str = "0.1.0"

    db_host: str = "localhost"
    db_port: int = 5433
    business_db_user: str = "studyhelper"
    business_db_password: str = "studyhelper123"
    business_db_name: str = "studyhelper"

    redis_host: str = "localhost"
    redis_port: int = 6380
    redis_password: str = "studyhelper123"

    minio_endpoint: str = "localhost:9100"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "studyhelper"
    asset_storage_path: str = "/tmp/studyhelper-assets"
    asset_base_url: str = "/assets"
    upload_max_image_dimension: int = 1600
    upload_jpeg_quality: int = 85
    upload_webp_quality: int = 85

    dify_api_url: str = "http://localhost:5001"
    dify_api_key: str = Field(default="your-dify-app-api-key", repr=False)

    sandbox_timeout: int = 5
    sandbox_memory_limit: str = "256m"
    sandbox_cpu_limit: float = 1.0
    sandbox_image: str = "studyhelper-code-sandbox:latest"

    @property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.business_db_user}:{self.business_db_password}"
            f"@{self.db_host}:{self.db_port}/{self.business_db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
