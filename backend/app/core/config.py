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
    upload_max_image_dimension: int = 3000
    upload_jpeg_quality: int = 92
    upload_webp_quality: int = 92
    agent_trace_enabled: bool = False
    agent_trace_dir: str = "/tmp/studyhelper-agent-traces"

    # LLM 配置：默认供应商 + 按模型可选覆盖
    llm_api_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = Field(default="your-llm-api-key", repr=False)

    # 6 个场景各自配模型名，url/key 可选覆盖（None 则用默认值）
    llm_model_planning: str = "qwen3.6-plus"
    llm_model_planning_url: str | None = None
    llm_model_planning_key: str | None = None

    llm_model_question_parse: str = "qwen3.6-plus"
    llm_model_question_parse_url: str | None = None
    llm_model_question_parse_key: str | None = None

    llm_model_solving: str = "qwen3.6-plus"
    llm_model_solving_url: str | None = None
    llm_model_solving_key: str | None = None

    llm_model_reflexion: str = "qwen3.6-plus"
    llm_model_reflexion_url: str | None = None
    llm_model_reflexion_key: str | None = None

    llm_model_vision: str = "qwen-vl-max-latest"
    llm_model_vision_url: str | None = None
    llm_model_vision_key: str | None = None

    llm_model_knowledge: str = "qwen3.6-plus"
    llm_model_knowledge_url: str | None = None
    llm_model_knowledge_key: str | None = None

    llm_model_figure_trigger: str = "qwen3.6-plus"
    llm_model_figure_trigger_url: str | None = None
    llm_model_figure_trigger_key: str | None = None

    llm_model_figure_goal: str = "qwen3.6-plus"
    llm_model_figure_goal_url: str | None = None
    llm_model_figure_goal_key: str | None = None

    llm_model_figure_draw: str = "qwen3.6-plus"
    llm_model_figure_draw_url: str | None = None
    llm_model_figure_draw_key: str | None = None

    llm_model_figure_revision: str = "qwen3.6-plus"
    llm_model_figure_revision_url: str | None = None
    llm_model_figure_revision_key: str | None = None

    llm_model_figure_semantic_inspection: str = "qwen-vl-max-latest"
    llm_model_figure_semantic_inspection_url: str | None = None
    llm_model_figure_semantic_inspection_key: str | None = None
    figure_semantic_inspection_enabled: bool = False
    pre_figure_reflexion_enabled: bool = False
    figure_trigger_llm_enabled: bool = True
    figure_goal_check_llm_enabled: bool = True
    figure_target_crop_vision_enabled: bool = False
    figure_overlay_revision_enabled: bool = True
    figure_code_revision_enabled: bool = True

    sandbox_timeout: int = 5
    sandbox_memory_limit: str = "256m"
    sandbox_cpu_limit: float = 1.0
    sandbox_image: str = "studyhelper-code-sandbox:latest"

    # CORS：开发环境填 ["*"] 或具体 origin，生产环境由 Nginx 同源代理可留空
    cors_allow_origins: list[str] = Field(default_factory=list)

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
