# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from pathlib import Path
from types import SimpleNamespace

from app.agent.tracing import create_agent_trace_recorder


def test_create_agent_trace_recorder_is_disabled_by_default(tmp_path):
    settings = SimpleNamespace(agent_trace_enabled=False, agent_trace_dir=str(tmp_path))

    recorder = create_agent_trace_recorder(
        settings=settings,
        session_id="session-1",
        client_user_id="anon-1",
        message="请解题",
        asset_ids=["asset-1"],
    )

    assert recorder is None
    assert list(tmp_path.iterdir()) == []


def test_agent_trace_recorder_writes_jsonl_trace(tmp_path):
    settings = SimpleNamespace(agent_trace_enabled=True, agent_trace_dir=str(tmp_path))

    recorder = create_agent_trace_recorder(
        settings=settings,
        session_id="session-1",
        client_user_id="anon-1",
        message="请解题",
        asset_ids=["asset-1"],
    )

    assert recorder is not None
    recorder.record("planning_result", {"strategy": "direct_answer"})
    recorder.close(status="ok", data={"message_id": "msg-1"})

    trace_files = list(Path(tmp_path).rglob("*.jsonl"))
    assert len(trace_files) == 1
    content = trace_files[0].read_text(encoding="utf-8").splitlines()
    assert any('"stage": "request_start"' in line for line in content)
    assert any('"stage": "planning_result"' in line for line in content)
    assert any('"stage": "trace_end"' in line for line in content)


def test_agent_trace_recorder_writes_stage_files_under_session_directory(tmp_path):
    settings = SimpleNamespace(agent_trace_enabled=True, agent_trace_dir=str(tmp_path))

    recorder = create_agent_trace_recorder(
        settings=settings,
        session_id="session-1",
        client_user_id="anon-1",
        message="请解题",
        asset_ids=["asset-1"],
    )

    assert recorder is not None
    recorder.record("figure_goal", {"expected_auxiliary": ["连接 CF"]})
    recorder.record("figure_draw_code", {"code": "plt.plot([0], [0])"})
    recorder.close(status="ok", data={"message_id": "msg-1"})

    trace_files = list(Path(tmp_path).rglob("*.jsonl"))
    assert len(trace_files) == 1
    trace_dir = trace_files[0].parent
    stage_files = {path.name for path in trace_dir.glob("*.json")}
    assert "0001_request_start.json" in stage_files
    assert "0002_figure_goal.json" in stage_files
    assert "0003_figure_draw_code.json" in stage_files
    assert "0004_trace_end.json" in stage_files
