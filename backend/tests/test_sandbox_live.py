# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.sandbox import PythonFigureRequest
from app.services.assets import InMemoryAssetRepository
from app.services.sandbox import DockerPythonFigureSandboxService
from app.services.storage import LocalAssetStorage


@pytest.mark.asyncio
async def test_docker_python_figure_sandbox_live(tmp_path):
    if os.getenv("RUN_DOCKER_SANDBOX_LIVE") != "1":
        pytest.skip("Set RUN_DOCKER_SANDBOX_LIVE=1 to run Docker sandbox live test")

    repository = InMemoryAssetRepository()
    service = DockerPythonFigureSandboxService(
        settings=Settings(sandbox_timeout=10),
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    response = await service.render_figure(
        PythonFigureRequest(
            code="import matplotlib.pyplot as plt\nplt.plot([0, 1], [0, 1])",
            session_id="session-live",
            message_id="message-live",
            width=320,
            height=240,
        )
    )

    asset = repository.assets[response["asset_id"]]
    output_path = Path(tmp_path) / asset["object_key"]
    assert response["image_url"].startswith("/assets/figures/")
    assert asset["asset_type"] == "sandbox_image"
    assert asset["session_id"] == "session-live"
    assert asset["message_id"] == "message-live"
    assert asset["mime_type"] == "image/png"
    assert output_path.exists()
    assert output_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
