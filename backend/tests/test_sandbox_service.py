# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import base64
import io
import tarfile

import pytest

from app.core.config import Settings
from app.core.exceptions import StudyHelperError
from app.schemas.sandbox import PythonFigureRequest
from app.services.assets import InMemoryAssetRepository
from app.services.sandbox import DockerPythonFigureSandboxService, InMemoryPythonFigureSandboxService
from app.services.storage import LocalAssetStorage


class TimeoutContainer:
    def wait(self, timeout: int):
        raise TimeoutError("container timed out")


@pytest.mark.asyncio
async def test_in_memory_sandbox_persists_generated_png_asset(tmp_path):
    repository = InMemoryAssetRepository()
    service = InMemoryPythonFigureSandboxService(
        asset_repository=repository,
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    response = await service.render_figure(
        PythonFigureRequest(
            code="import matplotlib.pyplot as plt\nplt.plot([0, 1], [0, 1])",
            session_id="session-1",
            message_id="message-1",
            width=640,
            height=480,
        )
    )

    stored_asset = repository.assets[response["asset_id"]]
    assert response["image_url"].startswith("/assets/figures/")
    assert stored_asset["asset_type"] == "sandbox_image"
    assert stored_asset["session_id"] == "session-1"
    assert stored_asset["message_id"] == "message-1"
    assert stored_asset["mime_type"] == "image/png"
    assert stored_asset["width"] == 640
    assert stored_asset["height"] == 480
    assert (tmp_path / stored_asset["object_key"]).exists()


@pytest.mark.asyncio
async def test_sandbox_rejects_python_syntax_error():
    service = InMemoryPythonFigureSandboxService()

    with pytest.raises(StudyHelperError) as exc_info:
        await service.render_figure(PythonFigureRequest(code="def broken(:"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "sandbox_syntax_error"


def test_docker_sandbox_extract_output_rejects_missing_png(tmp_path):
    service = DockerPythonFigureSandboxService(
        settings=Settings(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        content = b"not a png"
        info = tarfile.TarInfo("not_output.txt")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    archive.seek(0)

    with pytest.raises(StudyHelperError) as exc_info:
        service._read_output_png([archive.getvalue()])

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "sandbox_no_output"


def test_docker_sandbox_extract_output_rejects_non_png_content(tmp_path):
    service = DockerPythonFigureSandboxService(
        settings=Settings(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        content = b"not a png"
        info = tarfile.TarInfo("output.png")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    archive.seek(0)

    with pytest.raises(StudyHelperError) as exc_info:
        service._read_output_png([archive.getvalue()])

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "sandbox_invalid_output"


def test_docker_sandbox_stdout_output_rejects_missing_png_marker(tmp_path):
    service = DockerPythonFigureSandboxService(
        settings=Settings(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    with pytest.raises(StudyHelperError) as exc_info:
        service._read_output_png_from_stdout("plain stdout without image")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "sandbox_no_output"


def test_docker_sandbox_stdout_output_rejects_non_png_content(tmp_path):
    service = DockerPythonFigureSandboxService(
        settings=Settings(),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )
    encoded = base64.b64encode(b"not a png").decode("ascii")

    with pytest.raises(StudyHelperError) as exc_info:
        service._read_output_png_from_stdout(f"STUDYHELPER_PNG_BASE64:{encoded}")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "sandbox_invalid_output"


def test_docker_sandbox_wait_converts_timeout_to_sandbox_error(tmp_path):
    service = DockerPythonFigureSandboxService(
        settings=Settings(sandbox_timeout=1),
        asset_repository=InMemoryAssetRepository(),
        storage=LocalAssetStorage(root_dir=tmp_path, base_url="/assets"),
    )

    with pytest.raises(StudyHelperError) as exc_info:
        service._wait_for_container(TimeoutContainer())

    assert exc_info.value.status_code == 408
    assert exc_info.value.code == "sandbox_timeout"
