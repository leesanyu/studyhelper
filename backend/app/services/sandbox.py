# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import ast
import io
import tarfile
import time
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.core.config import Settings
from app.core.exceptions import StudyHelperError
from app.schemas.sandbox import PythonFigureRequest


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
    def __init__(self, validator: PythonFigureCodeValidator | None = None) -> None:
        self._validator = validator or PythonFigureCodeValidator()

    async def render_figure(self, request: PythonFigureRequest) -> dict:
        started_at = time.monotonic()
        self._validator.validate(request.code)
        asset_id = str(uuid4())
        return {
            "asset_id": asset_id,
            "image_url": f"/assets/{asset_id}.png",
            "mime_type": "image/png",
            "width": request.width,
            "height": request.height,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "stderr": "",
        }


class DockerPythonFigureSandboxService:
    def __init__(
        self,
        settings: Settings,
        validator: PythonFigureCodeValidator | None = None,
    ) -> None:
        self._settings = settings
        self._validator = validator or PythonFigureCodeValidator()

    async def render_figure(self, request: PythonFigureRequest) -> dict:
        self._validator.validate(request.code)
        return self._run_container(request)

    def _run_container(self, request: PythonFigureRequest) -> dict:
        try:
            import docker
            from docker.errors import DockerException, NotFound
        except ImportError as exc:
            raise StudyHelperError("Docker SDK is not installed", 500, "sandbox_unavailable") from exc

        started_at = time.monotonic()
        asset_id = str(uuid4())
        output_dir = Path("/tmp/studyhelper-assets")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{asset_id}.png"
        client = docker.from_env()
        container = None

        try:
            container = client.containers.create(
                self._settings.sandbox_image,
                command=["python", "/tmp/work/run.py"],
                detach=True,
                environment={"MPLCONFIGDIR": "/tmp/mplconfig"},
                mem_limit=self._settings.sandbox_memory_limit,
                nano_cpus=int(self._settings.sandbox_cpu_limit * 1_000_000_000),
                network_disabled=True,
                read_only=True,
                tmpfs={
                    "/tmp/work": "rw,noexec,nosuid,size=64m",
                    "/tmp/mplconfig": "rw,noexec,nosuid,size=32m",
                },
                user="sandbox",
                working_dir="/tmp/work",
            )
            container.put_archive("/tmp/work", self._build_script_archive(request))
            container.start()
            result = container.wait(timeout=self._settings.sandbox_timeout)
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            if result.get("StatusCode") != 0:
                raise StudyHelperError(
                    stderr[-500:] or "Python figure execution failed",
                    400,
                    "sandbox_execution_failed",
                )

            self._extract_output_png(container, output_path)
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
            "image_url": f"/assets/{asset_id}.png",
            "mime_type": "image/png",
            "width": request.width,
            "height": request.height,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "stderr": stderr[-500:],
        }

    def _build_script_archive(self, request: PythonFigureRequest) -> bytes:
        script = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            f"plt.figure(figsize=({request.width / 100:.2f}, {request.height / 100:.2f}), dpi=100)\n"
            f"{request.code}\n"
            "plt.gcf().set_size_inches("
            f"{request.width / 100:.2f}, {request.height / 100:.2f}, forward=True)\n"
            "plt.savefig('/tmp/work/output.png', format='png')\n"
        ).encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo("run.py")
            info.size = len(script)
            archive.addfile(info, io.BytesIO(script))
        buffer.seek(0)
        return buffer.read()

    def _extract_output_png(self, container: object, output_path: Path) -> None:
        stream, _stat = container.get_archive("/tmp/work/output.png")
        buffer = io.BytesIO()
        for chunk in stream:
            buffer.write(chunk)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            member = archive.getmember("output.png")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise StudyHelperError("Sandbox did not produce a png file", 400, "sandbox_no_output")
            output_path.write_bytes(extracted.read())
