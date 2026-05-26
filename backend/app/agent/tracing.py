# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent 调试轨迹落盘。

默认关闭；开启后将每次提交的关键步骤写入本地 JSONL 文件，便于复盘。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def create_agent_trace_recorder(
    *,
    settings: Any | None,
    session_id: str | None,
    client_user_id: str,
    message: str,
    asset_ids: list[str],
) -> "AgentTraceRecorder | None":
    """按配置创建轨迹记录器。"""
    if settings is None or not getattr(settings, "agent_trace_enabled", False):
        return None

    trace_dir = Path(
        getattr(settings, "agent_trace_dir", "/tmp/studyhelper-agent-traces")
    )
    return AgentTraceRecorder(
        trace_dir=trace_dir,
        session_id=session_id,
        client_user_id=client_user_id,
        message=message,
        asset_ids=asset_ids,
    )


class AgentTraceRecorder:
    """单次聊天请求的 JSONL 轨迹记录器。"""

    def __init__(
        self,
        *,
        trace_dir: Path,
        session_id: str | None,
        client_user_id: str,
        message: str,
        asset_ids: list[str],
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        request_id = uuid4().hex[:8]
        safe_session_id = _safe_segment(session_id or "local-session")

        trace_run_dir = trace_dir / timestamp[:8] / f"{timestamp}_{safe_session_id}_{request_id}"
        trace_run_dir.mkdir(parents=True, exist_ok=True)
        self.path = trace_run_dir / "trace.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")
        self._closed = False
        self._run_dir = trace_run_dir
        self._sequence = 0

        self.record(
            "request_start",
            {
                "session_id": session_id,
                "client_user_id": client_user_id,
                "message": message,
                "asset_ids": asset_ids,
            },
        )

    def record(self, stage: str, data: dict[str, Any]) -> None:
        if self._closed:
            return
        self._sequence += 1
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "data": data,
        }
        self._fh.write(json.dumps(entry, ensure_ascii=False, default=_json_default))
        self._fh.write("\n")
        self._fh.flush()
        stage_path = self._run_dir / f"{self._sequence:04d}_{_safe_segment(stage)}.json"
        stage_path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    def close(self, *, status: str, data: dict[str, Any] | None = None) -> None:
        if self._closed:
            return
        self.record(
            "trace_end",
            {
                "status": status,
                **(data or {}),
            },
        )
        self._fh.close()
        self._closed = True


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")[:48] or "trace"


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)
