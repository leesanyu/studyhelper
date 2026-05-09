# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import ast
import base64
import io
import tarfile
import time
from typing import Protocol
from uuid import uuid4

from PIL import Image

from app.core.config import Settings
from app.core.exceptions import StudyHelperError
from app.schemas.sandbox import PythonFigureRequest
from app.services.assets import AssetCreate, AssetRepository
from app.services.storage import AssetStorage


class PythonFigureSandboxService(Protocol):
    async def render_figure(self, request: PythonFigureRequest) -> dict:
        ...


class PythonFigureCodeValidator:
    banned_import_roots = {
        "ctypes",
        "ftplib",
        "glob",
        "http",
        "importlib",
        "multiprocessing",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "tempfile",
        "threading",
        "urllib",
    }
    banned_calls = {"__import__", "compile", "eval", "exec", "input", "open"}
    banned_attributes = {
        "accept",
        "bind",
        "chdir",
        "connect",
        "listen",
        "makedirs",
        "mkdir",
        "popen",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "rmtree",
        "system",
        "unlink",
    }
    banned_literals = {"/etc", "/proc", "/root", "/var/run", "../", "..\\"}

    def validate(self, code: str) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise StudyHelperError(
                f"Python code syntax error: {exc.msg}", 400, "sandbox_syntax_error"
            ) from exc

        for literal in self.banned_literals:
            if literal in code:
                raise self._rejected(f"Path access is not allowed: {literal}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_import(alias.name)
            elif isinstance(node, ast.ImportFrom):
                self._check_import(node.module or "")
            elif isinstance(node, ast.Call):
                self._check_call(node)
            elif isinstance(node, ast.Attribute) and node.attr in self.banned_attributes:
                raise self._rejected(f"Operation is not allowed: {node.attr}")

    def _check_import(self, module_name: str) -> None:
        root = module_name.split(".", 1)[0]
        if root in self.banned_import_roots:
            raise self._rejected(f"Import is not allowed: {root}")

    def _check_call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.banned_calls:
            raise self._rejected(f"Call is not allowed: {func.id}")
        if isinstance(func, ast.Attribute) and func.attr in self.banned_attributes:
            raise self._rejected(f"Operation is not allowed: {func.attr}")

    def _rejected(self, message: str) -> StudyHelperError:
        return StudyHelperError(message, 400, "sandbox_rejected")


class InMemoryPythonFigureSandboxService:
    def __init__(
        self,
        validator: PythonFigureCodeValidator | None = None,
        asset_repository: AssetRepository | None = None,
        storage: AssetStorage | None = None,
    ) -> None:
        self._validator = validator or PythonFigureCodeValidator()
        self._asset_repository = asset_repository
        self._storage = storage

    async def render_figure(self, request: PythonFigureRequest) -> dict:
        started_at = time.monotonic()
        self._validator.validate(request.code)
        png_content = self._placeholder_png(width=request.width, height=request.height)
        asset_id = str(uuid4())
        image_url = f"/assets/{asset_id}.png"
        if self._asset_repository is not None and self._storage is not None:
            stored = await self._storage.save(
                asset_id=asset_id,
                content=png_content,
                extension=".png",
                prefix="figures",
            )
            image_url = stored["url"]
            await self._asset_repository.create_asset(
                AssetCreate(
                    asset_id=asset_id,
                    asset_type="sandbox_image",
                    storage_backend=stored["storage_backend"],
                    object_key=stored["object_key"],
                    url=stored["url"],
                    dify_file_id=None,
                    filename=f"{asset_id}.png",
                    mime_type="image/png",
                    size_bytes=len(png_content),
                    width=request.width,
                    height=request.height,
                    session_id=request.session_id,
                    message_id=request.message_id,
                    metadata={"stderr": ""},
                )
            )
        return {
            "asset_id": asset_id,
            "image_url": image_url,
            "mime_type": "image/png",
            "width": request.width,
            "height": request.height,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "stderr": "",
        }

    def _placeholder_png(self, *, width: int, height: int) -> bytes:
        image = Image.new("RGB", (width, height), color=(255, 255, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


class DockerPythonFigureSandboxService:
    def __init__(
        self,
        settings: Settings,
        validator: PythonFigureCodeValidator | None = None,
        asset_repository: AssetRepository | None = None,
        storage: AssetStorage | None = None,
    ) -> None:
        self._settings = settings
        self._validator = validator or PythonFigureCodeValidator()
        self._asset_repository = asset_repository
        self._storage = storage

    async def render_figure(self, request: PythonFigureRequest) -> dict:
        self._validator.validate(request.code)
        return await self._run_container(request)

    async def _run_container(self, request: PythonFigureRequest) -> dict:
        try:
            import docker
            from docker.errors import DockerException, NotFound
        except ImportError as exc:
            raise StudyHelperError("Docker SDK is not installed", 500, "sandbox_unavailable") from exc

        started_at = time.monotonic()
        asset_id = str(uuid4())
        client = docker.from_env()
        container = None

        try:
            container = client.containers.create(
                self._settings.sandbox_image,
                command=["python", "-c", self._build_script_source(request)],
                detach=True,
                environment={"MPLCONFIGDIR": "/tmp/mplconfig"},
                mem_limit=self._settings.sandbox_memory_limit,
                nano_cpus=int(self._settings.sandbox_cpu_limit * 1_000_000_000),
                network_disabled=True,
                read_only=True,
                tmpfs={
                    "/tmp/work": "rw,noexec,nosuid,size=64m,mode=1777",
                    "/tmp/mplconfig": "rw,noexec,nosuid,size=32m,mode=1777",
                },
                user="sandbox",
                working_dir="/tmp/work",
            )
            container.start()
            result = self._wait_for_container(container)
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")

            if result.get("StatusCode") != 0:
                raise StudyHelperError(
                    stderr[-500:] or "Python figure execution failed",
                    400,
                    "sandbox_execution_failed",
                )

            png_content = self._read_output_png_from_stdout(stdout)
            image_url = await self._persist_asset(
                asset_id=asset_id,
                request=request,
                png_content=png_content,
                stderr=stderr[-500:],
            )
        except NotFound as exc:
            raise StudyHelperError(
                f"Sandbox image not found: {self._settings.sandbox_image}",
                500,
                "sandbox_unavailable",
            ) from exc
        except DockerException as exc:
            raise StudyHelperError(str(exc), 500, "sandbox_unavailable") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

        return {
            "asset_id": asset_id,
            "image_url": image_url,
            "mime_type": "image/png",
            "width": request.width,
            "height": request.height,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "stderr": stderr[-500:],
        }

    def _wait_for_container(self, container: object) -> dict:
        try:
            return container.wait(timeout=self._settings.sandbox_timeout)
        except TimeoutError as exc:
            raise StudyHelperError(
                "Python figure execution timed out",
                408,
                "sandbox_timeout",
            ) from exc
        except Exception as exc:
            if exc.__class__.__name__ in {"ReadTimeout", "Timeout"}:
                raise StudyHelperError(
                    "Python figure execution timed out",
                    408,
                    "sandbox_timeout",
                ) from exc
            raise

    def _build_script_source(self, request: PythonFigureRequest) -> str:
        return (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import base64\n"
            "from pathlib import Path\n"
            "import sys\n"
            "import matplotlib.pyplot as plt\n"
            f"plt.figure(figsize=({request.width / 100:.2f}, {request.height / 100:.2f}), dpi=100)\n"
            f"{request.code}\n"
            "plt.gcf().set_size_inches("
            f"{request.width / 100:.2f}, {request.height / 100:.2f}, forward=True)\n"
            "plt.savefig('/tmp/work/output.png', format='png')\n"
            "sys.stdout.write('STUDYHELPER_PNG_BASE64:' + "
            "base64.b64encode(Path('/tmp/work/output.png').read_bytes()).decode('ascii') + '\\n')\n"
        )

    def _build_script_archive(self, request: PythonFigureRequest) -> bytes:
        script = self._build_script_source(request).encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo("run.py")
            info.size = len(script)
            archive.addfile(info, io.BytesIO(script))
        buffer.seek(0)
        return buffer.read()

    def _extract_output_png(self, container: object) -> bytes:
        stream, _stat = container.get_archive("/tmp/work/output.png")
        return self._read_output_png(stream)

    def _read_output_png(self, stream: object) -> bytes:
        buffer = io.BytesIO()
        for chunk in stream:
            buffer.write(chunk)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            try:
                member = archive.getmember("output.png")
            except KeyError as exc:
                raise StudyHelperError(
                    "Sandbox did not produce a png file", 400, "sandbox_no_output"
                ) from exc
            extracted = archive.extractfile(member)
            if extracted is None:
                raise StudyHelperError("Sandbox did not produce a png file", 400, "sandbox_no_output")
            content = extracted.read()
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise StudyHelperError("Sandbox output is not a png file", 400, "sandbox_invalid_output")
        return content

    def _read_output_png_from_stdout(self, stdout: str) -> bytes:
        marker = "STUDYHELPER_PNG_BASE64:"
        for line in stdout.splitlines():
            if not line.startswith(marker):
                continue
            try:
                content = base64.b64decode(line.removeprefix(marker), validate=True)
            except ValueError as exc:
                raise StudyHelperError(
                    "Sandbox output is not a png file", 400, "sandbox_invalid_output"
                ) from exc
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise StudyHelperError(
                    "Sandbox output is not a png file", 400, "sandbox_invalid_output"
                )
            return content
        raise StudyHelperError("Sandbox did not produce a png file", 400, "sandbox_no_output")

    async def _persist_asset(
        self,
        *,
        asset_id: str,
        request: PythonFigureRequest,
        png_content: bytes,
        stderr: str,
    ) -> str:
        if self._asset_repository is None or self._storage is None:
            return f"/assets/{asset_id}.png"
        stored = await self._storage.save(
            asset_id=asset_id,
            content=png_content,
            extension=".png",
            prefix="figures",
        )
        await self._asset_repository.create_asset(
            AssetCreate(
                asset_id=asset_id,
                asset_type="sandbox_image",
                storage_backend=stored["storage_backend"],
                object_key=stored["object_key"],
                url=stored["url"],
                dify_file_id=None,
                filename=f"{asset_id}.png",
                mime_type="image/png",
                size_bytes=len(png_content),
                width=request.width,
                height=request.height,
                session_id=request.session_id,
                message_id=request.message_id,
                metadata={"stderr": stderr},
            )
        )
        return stored["url"]
