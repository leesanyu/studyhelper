# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""AgentService 结构化几何分支集成测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from app.agent.llm_client import ChatResponse, StreamEnd, TextDelta
from app.agent.service import AgentService
from app.services.assets import InMemoryAssetRepository


class _AsyncChunkIterator:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class FakeGeometryLLM:
    def __init__(self, planning_tool_calls: list[str] | None = None) -> None:
        self._planning_tool_calls = (
            ["process_question"] if planning_tool_calls is None else planning_tool_calls
        )
        self.chat_json_calls: list[str] = []
        self.stream_messages = None

    async def chat_json(self, *, messages, scene, temperature=0.1):
        self.chat_json_calls.append(scene)
        if scene == "planning":
            return ChatResponse(content=json.dumps({
                "question_type": "logical_calculation",
                "strategy": "direct_answer",
                "tool_calls": self._planning_tool_calls,
                "need_deep_reflexion": False,
            }))
        if scene in {"vision", "question_parse"}:
            return ChatResponse(content=json.dumps({
                "subject": "初中数学",
                "question_text": "如图，连接 CF。",
                "has_figure": True,
                "diagram_description": "A、E、C、F 四点",
                "visual_observation": {
                    "points": [
                        {"id": "A", "coordinate": [0, 0]},
                        {"id": "E", "coordinate": [1, 0]},
                        {"id": "C", "coordinate": [0, 1]},
                    ],
                    "drawn_segments": [{"endpoints": ["A", "E"]}],
                    "marks": [],
                    "uncertain": [],
                },
                "question_count": 1,
            }))
        if scene == "knowledge":
            return ChatResponse(content=json.dumps({
                "subject": "初中数学",
                "knowledge_points": ["几何辅助线"],
                "difficulty": "中等",
                "grade_level": "八年级",
            }))
        return ChatResponse(content=json.dumps({"had_violation": False}))

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        return ChatResponse(content="")

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF。"),
            TextDelta(text="\n证明如下。```python:figure\nplt.plot([0],[0])\n```"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeLegacyFigureLLM(FakeGeometryLLM):
    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="先画出辅助线帮助理解。"),
            TextDelta(text="\n```python:figure\nplt.plot([0], [0])\n```"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeFigureAgentFallbackLLM(FakeGeometryLLM):
    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_trigger":
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({
                "figure_needed": True,
                "reason": "解答使用了辅助线",
                "auxiliary_intent": "连接 CF。",
                "confidence": 0.8,
                "existing_python_figure": "",
            }))
        if scene == "figure_goal":
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({
                "goal_status": "ready",
                "normalized_auxiliary_intent": "连接 CF。",
                "expected_auxiliary": ["connect CF"],
                "original_figure_elements": ["A/E/C labels", "segment AE"],
                "layout_hint": {"type": "schematic"},
                "style_requirements": {"auxiliary_lines": "red dashed"},
                "warnings": [],
            }))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_draw":
            return ChatResponse(content="```python:figure\nplt.plot([0], [0])\n```")
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】连接 CF。"),
            TextDelta(text="\n利用辅助线证明。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeMalformedTriggerFigureAgentLLM(FakeFigureAgentFallbackLLM):
    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_trigger":
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({"figure_needed": False}))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="本题涉及三角形全等，需要补充图形说明。"),
            TextDelta(text="\n证明如下。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeRevisionFigureAgentLLM(FakeFigureAgentFallbackLLM):
    def __init__(self) -> None:
        super().__init__()
        self.figure_draw_calls = 0
        self.revision_calls = 0

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_draw":
            self.figure_draw_calls += 1
            return ChatResponse(content="```python:figure\nraise RuntimeError('bad draw')\n```")
        if scene == "figure_revision":
            self.revision_calls += 1
            joined = "\n".join(str(message["content"]) for message in messages)
            assert "bad draw" in joined
            return ChatResponse(content="```python:figure\nplt.plot([1], [1])\n```")
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )


class FakeRedrawPlanFigureAgentLLM(FakeFigureAgentFallbackLLM):
    def __init__(self) -> None:
        super().__init__()
        self.goal_calls = 0
        self.figure_draw_calls = 0
        self.revision_calls = 0

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_goal":
            self.chat_json_calls.append(scene)
            self.goal_calls += 1
            return ChatResponse(content=json.dumps({
                "goal_status": "ready",
                "normalized_auxiliary_intent": "连接 CF。",
                "expected_auxiliary": [f"connect CF attempt {self.goal_calls}"],
                "original_figure_elements": ["A/E/C labels", "segment AE"],
                "layout_hint": {"type": "schematic"},
                "style_requirements": {"auxiliary_lines": "red dashed"},
                "warnings": [],
            }))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_draw":
            self.figure_draw_calls += 1
            if self.figure_draw_calls == 1:
                return ChatResponse(content="```python:figure\nraise RuntimeError('bad first plan')\n```")
            return ChatResponse(content="```python:figure\nplt.plot([2], [2])\n```")
        if scene == "figure_revision":
            self.revision_calls += 1
            return ChatResponse(content=json.dumps({
                "status": "need_redraw_plan",
                "reason": "绘图目标需要重新整理",
            }, ensure_ascii=False))
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )


class FakeSemanticRevisionFigureAgentLLM(FakeFigureAgentFallbackLLM):
    def __init__(self) -> None:
        super().__init__()
        self.semantic_calls = 0
        self.revision_calls = 0

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_semantic_inspection":
            self.chat_json_calls.append(scene)
            self.semantic_calls += 1
            return ChatResponse(content=json.dumps({
                "keep": ["原图骨架"],
                "missing": ["辅助线 CF"],
                "wrong": [],
                "style_issues": [],
                "score": 45,
                "next_action": "revise_code",
                "suggested_fix": "补画红色虚线 CF",
            }, ensure_ascii=False))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_revision":
            self.revision_calls += 1
            joined = "\n".join(str(message["content"]) for message in messages)
            assert "辅助线 CF" in joined
            return ChatResponse(content="```python:figure\nplt.plot([3], [3])\n```")
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )


class FakeStructuredCandidateAndFigureAgentLLM(FakeGeometryLLM):
    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_trigger":
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({
                "figure_needed": True,
                "reason": "结构化候选图仍需 Figure Agent 复核",
                "auxiliary_intent": "延长 AE 至 F，使 EF=AE，连接 CF、BF。",
                "confidence": 0.9,
                "existing_python_figure": "",
            }))
        if scene == "figure_goal":
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({
                "goal_status": "ready",
                "normalized_auxiliary_intent": "延长 AE 至 F，使 EF=AE，连接 CF、BF。",
                "expected_auxiliary": ["extend AE to F", "connect CF", "connect BF"],
                "original_figure_elements": ["A/E/C/B labels", "segment AE", "segment CB"],
                "layout_hint": {"type": "schematic"},
                "style_requirements": {"auxiliary_lines": "red dashed"},
                "warnings": [],
            }))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_draw":
            return ChatResponse(content="```python:figure\nplt.plot([9], [9])\n```")
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )


class FakeStructuredCandidateRevisionLLM(FakeStructuredCandidateAndFigureAgentLLM):
    def __init__(self) -> None:
        super().__init__()
        self.semantic_calls = 0
        self.revision_calls = 0

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_semantic_inspection":
            self.chat_json_calls.append(scene)
            self.semantic_calls += 1
            joined = "\n".join(str(message["content"]) for message in messages)
            assert "structured_renderer" in joined
            return ChatResponse(content=json.dumps({
                "keep": ["原图骨架"],
                "missing": ["F 应位于 AE 延长线上", "辅助线 CF、BF"],
                "wrong": ["结构化候选把 F 画到了 A 的位置"],
                "style_issues": [],
                "score": 30,
                "next_action": "revise_code",
                "suggested_fix": "保留原图骨架，重新放置 F，并补画 CF、BF",
            }, ensure_ascii=False))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_revision":
            self.revision_calls += 1
            joined = "\n".join(str(message["content"]) for message in messages)
            assert "structured_renderer" in joined
            assert "结构化候选把 F 画到了 A 的位置" in joined
            return ChatResponse(content="```python:figure\nplt.plot([8], [8])\n```")
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )


class FakePerpendicularGeometryLLM(FakeGeometryLLM):
    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene in {"vision", "question_parse"}:
            return ChatResponse(content=json.dumps({
                "subject": "初中数学",
                "question_text": "如图，连接 BH，求证 AH⊥BH。",
                "has_figure": True,
                "diagram_description": "A、B、H 三点和 AH 线段",
                "visual_observation": {
                    "points": [
                        {"id": "A", "coordinate": [0, 0]},
                        {"id": "H", "coordinate": [2, 0]},
                        {"id": "B", "coordinate": [1, 1]},
                    ],
                    "drawn_segments": [{"endpoints": ["A", "H"]}],
                    "marks": [],
                    "uncertain": [],
                },
                "question_count": 1,
            }))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】过点B作BF⊥AH交直线AH于点F。"),
            TextDelta(text="\n下面证明。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeInvalidStructuredWithLegacyFigureLLM(FakePerpendicularGeometryLLM):
    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】过点Z作ZF⊥AH交直线AH于点F。"),
            TextDelta(text="\n```python:figure\nplt.plot([0], [0])\n```"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeCutLengthGeometryLLM(FakeGeometryLLM):
    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene in {"vision", "question_parse"}:
            return ChatResponse(content=json.dumps({
                "subject": "初中数学",
                "question_text": "如图，AH+2AE=BH，求证 AH⊥BH。",
                "has_figure": True,
                "diagram_description": "A、H、B 三点和 AH 线段",
                "visual_observation": {
                    "points": [
                        {"id": "A", "coordinate": [1, 1]},
                        {"id": "H", "coordinate": [2, 0]},
                        {"id": "B", "coordinate": [0, 0]},
                    ],
                    "drawn_segments": [{"endpoints": ["B", "H"]}],
                    "marks": [],
                    "uncertain": [],
                },
                "question_count": 1,
            }))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="观察 H,A,E 共线，试着在 BH 上截取一点 F，使 HF=AH。"),
            TextDelta(text="\n接下来把 BF 和 AE 联系起来。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeChainedPerpendicularGeometryLLM(FakeGeometryLLM):
    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene in {"vision", "question_parse"}:
            return ChatResponse(content=json.dumps({
                "subject": "初中数学",
                "question_text": "如图，连接 BH，求证 AH⊥BH。",
                "has_figure": True,
                "diagram_description": "A、B、C、H 四点和 AH 线段",
                "visual_observation": {
                    "points": [
                        {"id": "A", "coordinate": [0, 0]},
                        {"id": "H", "coordinate": [3, 0]},
                        {"id": "B", "coordinate": [1, 1]},
                        {"id": "C", "coordinate": [0, 1]},
                    ],
                    "drawn_segments": [{"endpoints": ["A", "H"]}],
                    "marks": [],
                    "uncertain": [],
                },
                "question_count": 1,
            }))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】过点B作BF⊥AH于点F，过点C作CG⊥BF于点G。"),
            TextDelta(text="\n下面证明。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])


class FakeSessionRepository:
    def __init__(self) -> None:
        self.context = {}
        self.updates = []

    async def get_session(self, session_id):
        return self.context

    async def update_context(self, session_id, **kwargs):
        self.updates.append(kwargs)
        self.context.update(kwargs)


class FakeMessageRepository:
    def __init__(self) -> None:
        self.created = []
        self._assistant_count = 0

    async def get_messages(self, session_id, limit=20):
        return []

    async def create_message(self, data):
        self.created.append(data)
        if getattr(data, "role", "") == "assistant":
            self._assistant_count += 1
            return {"message_id": f"assistant-{self._assistant_count}"}
        return {"message_id": f"user-{len(self.created)}"}


class RecoverableBrokenSessionRepository:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.updates = []

    async def get_session(self, session_id):
        raise RuntimeError("simulated context query failure")

    async def update_context(self, session_id, **kwargs):
        self.updates.append(kwargs)

    async def rollback(self):
        self.rollback_calls += 1


class FakeSandbox:
    def __init__(self) -> None:
        self.requests = []

    async def render_figure(self, request):
        self.requests.append(request)
        return {"asset_id": "asset-geometry", "image_url": "/assets/figures/asset-geometry.png"}


class FakeFailOnceSandbox(FakeSandbox):
    async def render_figure(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            raise RuntimeError("bad draw")
        return {"asset_id": "asset-revised", "image_url": "/assets/figures/asset-revised.png"}


class FakeSequencedSandbox(FakeSandbox):
    def __init__(self, results):
        super().__init__()
        self._results = iter(results)

    async def render_figure(self, request):
        self.requests.append(request)
        return next(self._results)


class FakeAssetRepository:
    def __init__(self, object_key: str = "") -> None:
        self._object_key = object_key

    async def get_assets_by_ids(self, asset_ids):
        return [{
            "asset_id": asset_ids[0],
            "mime_type": "image/png",
            "size_bytes": 12,
            "object_key": self._object_key,
        }]


class FakeSettings:
    def __init__(self, asset_storage_path: str) -> None:
        self.asset_storage_path = asset_storage_path


class FakeSemanticSettings(FakeSettings):
    figure_semantic_inspection_enabled = True


class FakeOverlayLLM(FakeFigureAgentFallbackLLM):
    def __init__(self) -> None:
        super().__init__()
        self.figure_draw_json_calls = 0

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_goal":
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({
                "goal_status": "ready",
                "render_mode": "overlay_on_crop",
                "target_diagram": "图2",
                "coordinate_space": "crop_pixels",
                "normalized_auxiliary_intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
                "expected_auxiliary": [
                    "F lies on the ray from A through E",
                    "CF is connected",
                    "BF is connected",
                ],
                "original_figure_elements": ["A/E/C/B labels", "segment AE"],
                "layout_hint": {
                    "type": "overlay_on_crop",
                    "directed_rays": [{"ray": "AE", "meaning": "从 A 经 E 向 E 外侧延长"}],
                },
                "style_requirements": {"auxiliary_lines": "red dashed"},
                "warnings": [],
            }, ensure_ascii=False))
        if scene == "vision":
            joined = "\n".join(str(message["content"]) for message in messages)
            self.chat_json_calls.append("vision:overlay")
            if "目标几何图裁剪" in joined:
                return ChatResponse(content=json.dumps({
                    "label": "图2",
                    "crop_box": [0, 0, 320, 220],
                    "confidence": 0.9,
                    "warnings": [],
                }, ensure_ascii=False))
            if "点位定位" in joined:
                return ChatResponse(content=json.dumps({
                    "points": {
                        "A": {"x": 80, "y": 120, "confidence": 0.95},
                        "E": {"x": 150, "y": 120, "confidence": 0.95},
                        "C": {"x": 90, "y": 40, "confidence": 0.95},
                        "B": {"x": 230, "y": 60, "confidence": 0.95},
                    },
                    "warnings": [],
                }, ensure_ascii=False))
        if scene == "figure_draw":
            self.figure_draw_json_calls += 1
            return ChatResponse(content=json.dumps({
                "plan_type": "overlay_on_crop",
                "coordinate_space": "crop_pixels",
                "intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
                "constructions": [
                    {
                        "op": "point_on_segment_by_distance",
                        "point": "F",
                        "ray": "AE",
                        "from": "A",
                        "distance": "2*AE",
                        "role": "construction",
                    },
                    {"op": "connect_points", "points": ["C", "F"], "role": "construction"},
                    {"op": "connect_points", "points": ["B", "F"], "role": "construction"},
                ],
                "warnings": [],
            }, ensure_ascii=False))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)

    async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
        if scene == "figure_draw":
            raise AssertionError("overlay-first should request JSON overlay plan")
        return await super().chat(
            messages=messages,
            scene=scene,
            temperature=temperature,
            response_format=response_format,
        )


class FakeOverlayWrongVisionCropLLM(FakeOverlayLLM):
    def __init__(self) -> None:
        super().__init__()
        self.target_crop_calls = 0
        self.point_location_calls = 0

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "vision":
            joined = "\n".join(str(message["content"]) for message in messages)
            self.chat_json_calls.append("vision:overlay")
            if "目标几何图裁剪" in joined:
                self.target_crop_calls += 1
                return ChatResponse(content=json.dumps({
                    "label": "图2",
                    "crop_box": [0, 0, 120, 100],
                    "confidence": 0.4,
                    "warnings": ["VLM 裁剪偏到页面左上角"],
                }, ensure_ascii=False))
            if "点位定位" in joined:
                self.point_location_calls += 1
                return ChatResponse(content=json.dumps({
                    "points": {
                        "A": {"x": 80, "y": 120, "confidence": 0.95},
                        "E": {"x": 150, "y": 120, "confidence": 0.95},
                        "C": {"x": 90, "y": 40, "confidence": 0.95},
                        "B": {"x": 230, "y": 60, "confidence": 0.95},
                    },
                    "warnings": [],
                }, ensure_ascii=False))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)


class FakePerpendicularOverlayLLM(FakeOverlayWrongVisionCropLLM):
    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】过点 C 作 CK⊥CE，且使 CK=CE（点 K 与点 B 位于直线 CE 同侧），连接 BK、KH。"),
            TextDelta(text="\n利用辅助线证明。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "vision":
            joined = "\n".join(str(message["content"]) for message in messages)
            if "目标几何图裁剪" in joined:
                self.chat_json_calls.append("vision:overlay")
                self.target_crop_calls += 1
                return ChatResponse(content=json.dumps({
                    "label": "图2",
                    "crop_box": [0, 0, 120, 100],
                    "confidence": 0.4,
                    "warnings": ["VLM 裁剪偏到页面左上角"],
                }, ensure_ascii=False))
            if "点位定位" in joined:
                self.chat_json_calls.append("vision:overlay")
                self.point_location_calls += 1
                return ChatResponse(content=json.dumps({
                    "points": {
                        "C": {"x": 90, "y": 220, "confidence": 0.95},
                        "E": {"x": 180, "y": 330, "confidence": 0.95},
                        "B": {"x": 270, "y": 330, "confidence": 0.95},
                        "H": {"x": 130, "y": 420, "confidence": 0.95},
                    },
                    "warnings": [],
                }, ensure_ascii=False))
            self.chat_json_calls.append(scene)
            return ChatResponse(content=json.dumps({
                "subject": "初中数学",
                "question_text": "第（2）问，如图2，证明 AH⊥BH。",
                "has_figure": True,
                "diagram_description": "图2 含点 A、B、C、D、E、H。",
                "visual_observation": {
                    "points": [{"id": key} for key in ["A", "B", "C", "D", "E", "H"]],
                    "drawn_segments": [{"endpoints": ["C", "E"]}, {"endpoints": ["C", "B"]}],
                    "marks": [],
                    "uncertain": [],
                },
                "question_count": 2,
            }, ensure_ascii=False))
        if scene in {"figure_goal", "figure_draw", "figure_revision"}:
            self.chat_json_calls.append(scene)
            raise AssertionError(f"{scene} should be skipped for local perpendicular overlay plan")
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)


class FakeOverlayMissingConnectionLLM(FakeOverlayLLM):
    def __init__(self) -> None:
        super().__init__()
        self.revision_calls = 0

    def stream_chat(self, *, messages, scene, temperature=0.7):
        self.stream_messages = messages
        return _AsyncChunkIterator([
            TextDelta(text="【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。"),
            TextDelta(text="\n利用辅助线证明。"),
            StreamEnd(usage={"total_tokens": 3}),
        ])

    async def chat_json(self, *, messages, scene, temperature=0.1):
        if scene == "figure_draw":
            self.figure_draw_json_calls += 1
            return ChatResponse(content=json.dumps({
                "plan_type": "overlay_on_crop",
                "coordinate_space": "crop_pixels",
                "intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
                "constructions": [
                    {
                        "op": "point_on_segment_by_distance",
                        "point": "F",
                        "ray": "AE",
                        "from": "A",
                        "distance": "2*AE",
                    },
                    {"op": "connect_points", "points": ["C", "F"]},
                ],
                "warnings": [],
            }, ensure_ascii=False))
        if scene == "figure_revision":
            self.revision_calls += 1
            joined = "\n".join(str(message["content"]) for message in messages)
            assert "BF" in joined
            return ChatResponse(content=json.dumps({
                "plan_type": "overlay_on_crop",
                "coordinate_space": "crop_pixels",
                "intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
                "constructions": [
                    {
                        "op": "point_on_segment_by_distance",
                        "point": "F",
                        "ray": "AE",
                        "from": "A",
                        "distance": "2*AE",
                    },
                    {"op": "connect_points", "points": ["C", "F"]},
                    {"op": "connect_points", "points": ["B", "F"]},
                ],
                "warnings": [],
            }, ensure_ascii=False))
        return await super().chat_json(messages=messages, scene=scene, temperature=temperature)


@pytest.mark.asyncio
async def test_agent_service_prefers_overlay_plan_for_image_geometry(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (320, 220), "white")
    draw = ImageDraw.Draw(image)
    c_vertex = (90, 82)
    draw.line([c_vertex, (80, 120)], fill="black", width=4)
    draw.line([c_vertex, (150, 120)], fill="black", width=4)
    draw.line([c_vertex, (230, 60)], fill="black", width=4)
    draw.text((90, 35), "C", fill="black")
    image.save(image_path)

    repository = InMemoryAssetRepository()
    repository.assets["asset-1"] = {
        "asset_id": "asset-1",
        "asset_type": "question_image",
        "storage_backend": "local",
        "object_key": object_key,
        "url": "/assets/uploads/asset-1.png",
        "filename": "asset-1.png",
        "mime_type": "image/png",
        "size_bytes": image_path.stat().st_size,
        "width": 320,
        "height": 220,
        "metadata": {},
    }
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=FakeOverlayLLM(),
        asset_repository=repository,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=SimpleNamespace(
            asset_storage_path=str(tmp_path),
            asset_base_url="/assets",
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path / "traces"),
            figure_target_crop_vision_enabled=True,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    figure_event = next(event for event in events if event["event"] == "figure_result")
    stored_asset = repository.assets[figure_event["data"]["asset_id"]]
    assert stored_asset["asset_type"] == "figure_overlay"
    assert figure_event["data"]["image_url"].startswith("/assets/figures/")
    assert sandbox.requests == []

    trace_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "traces").rglob("*.jsonl")
    )
    assert '"stage": "target_diagram_crop"' in trace_content
    assert '"stage": "point_location"' in trace_content
    assert '"stage": "point_snap"' in trace_content
    assert '"C": {"snapped": true' in trace_content
    assert '"stage": "overlay_plan"' in trace_content
    assert '"stage": "overlay_render_trace"' in trace_content


@pytest.mark.asyncio
async def test_agent_service_revises_overlay_when_programmatic_check_finds_missing_connection(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (320, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(80, 120), (150, 120)], fill="black", width=4)
    draw.line([(90, 40), (80, 120)], fill="black", width=4)
    draw.line([(230, 60), (80, 120)], fill="black", width=4)
    image.save(image_path)

    repository = InMemoryAssetRepository()
    repository.assets["asset-1"] = {
        "asset_id": "asset-1",
        "asset_type": "question_image",
        "storage_backend": "local",
        "object_key": object_key,
        "url": "/assets/uploads/asset-1.png",
        "filename": "asset-1.png",
        "mime_type": "image/png",
        "size_bytes": image_path.stat().st_size,
        "width": 320,
        "height": 220,
        "metadata": {},
    }
    llm = FakeOverlayMissingConnectionLLM()
    service = AgentService(
        llm_client=llm,
        asset_repository=repository,
        session_repository=FakeSessionRepository(),
        sandbox_service=FakeSandbox(),
        settings=SimpleNamespace(
            asset_storage_path=str(tmp_path),
            asset_base_url="/assets",
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path / "traces"),
            figure_target_crop_vision_enabled=True,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    assert any(event["event"] == "figure_result" for event in events)
    assert llm.revision_calls == 1
    trace_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "traces").rglob("*.jsonl")
    )
    assert '"stage": "overlay_programmatic_observation"' in trace_content
    assert '"stage": "overlay_revision_plan"' in trace_content


@pytest.mark.asyncio
async def test_agent_service_skips_trigger_llm_when_auxiliary_text_exists():
    llm = FakeFigureAgentFallbackLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    assert any(event["event"] == "figure_result" for event in events)
    assert "figure_trigger" not in llm.chat_json_calls
    assert "figure_goal" in llm.chat_json_calls
    assert len(sandbox.requests) == 1


@pytest.mark.asyncio
async def test_agent_service_uses_local_goal_when_goal_llm_disabled():
    llm = FakeFigureAgentFallbackLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=SimpleNamespace(
            figure_goal_check_llm_enabled=False,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    assert any(event["event"] == "figure_result" for event in events)
    assert "figure_goal" not in llm.chat_json_calls
    assert len(sandbox.requests) == 1


@pytest.mark.asyncio
async def test_agent_service_skips_overlay_revision_when_disabled(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (320, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(80, 120), (150, 120)], fill="black", width=4)
    draw.line([(90, 40), (80, 120)], fill="black", width=4)
    draw.line([(230, 60), (80, 120)], fill="black", width=4)
    image.save(image_path)

    repository = InMemoryAssetRepository()
    repository.assets["asset-1"] = {
        "asset_id": "asset-1",
        "asset_type": "question_image",
        "storage_backend": "local",
        "object_key": object_key,
        "url": "/assets/uploads/asset-1.png",
        "filename": "asset-1.png",
        "mime_type": "image/png",
        "size_bytes": image_path.stat().st_size,
        "width": 320,
        "height": 220,
        "metadata": {},
    }
    llm = FakeOverlayMissingConnectionLLM()
    service = AgentService(
        llm_client=llm,
        asset_repository=repository,
        session_repository=FakeSessionRepository(),
        sandbox_service=FakeSandbox(),
        settings=SimpleNamespace(
            asset_storage_path=str(tmp_path),
            asset_base_url="/assets",
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path / "traces"),
            figure_target_crop_vision_enabled=True,
            figure_overlay_revision_enabled=False,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    assert any(event["event"] == "figure_result" for event in events)
    assert llm.revision_calls == 0
    trace_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "traces").rglob("*.jsonl")
    )
    assert '"stage": "overlay_programmatic_observation"' in trace_content
    assert '"stage": "overlay_revision_skipped"' in trace_content


@pytest.mark.asyncio
async def test_agent_service_skips_code_revision_when_disabled():
    llm = FakeRevisionFigureAgentLLM()
    sandbox = FakeFailOnceSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=SimpleNamespace(
            figure_code_revision_enabled=False,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    assert any(
        event["event"] == "tool_result"
        and event["data"]["tool"] == "figure_agent"
        and event["data"]["data"]["status"] == "failed"
        for event in events
    )
    assert llm.revision_calls == 0
    assert len(sandbox.requests) == 1


@pytest.mark.asyncio
async def test_agent_service_uses_layout_crop_without_vlm_target_crop_for_point_location(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    for offset in (120, 380, 650):
        draw.line([(offset, 330), (offset + 90, 220), (offset + 180, 330), (offset, 330)], fill="black", width=4)
        draw.line([(offset + 80, 330), (offset + 120, 420)], fill="black", width=4)
    image.save(image_path)

    repository = InMemoryAssetRepository()
    repository.assets["asset-1"] = {
        "asset_id": "asset-1",
        "asset_type": "question_image",
        "storage_backend": "local",
        "object_key": object_key,
        "url": "/assets/uploads/asset-1.png",
        "filename": "asset-1.png",
        "mime_type": "image/png",
        "size_bytes": image_path.stat().st_size,
        "width": 900,
        "height": 600,
        "metadata": {},
    }
    sandbox = FakeSandbox()
    llm = FakeOverlayWrongVisionCropLLM()
    service = AgentService(
        llm_client=llm,
        asset_repository=repository,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=SimpleNamespace(
            asset_storage_path=str(tmp_path),
            asset_base_url="/assets",
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path / "traces"),
            figure_target_crop_vision_enabled=False,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    figure_event = next(event for event in events if event["event"] == "figure_result")
    stored_asset = repository.assets[figure_event["data"]["asset_id"]]
    assert stored_asset["asset_type"] == "figure_overlay"
    assert sandbox.requests == []
    assert llm.target_crop_calls == 0
    assert llm.point_location_calls == 1

    trace_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "traces").rglob("*.jsonl")
    )
    assert '"stage": "point_location_full_image"' not in trace_content
    assert '"source": "layout_component"' in trace_content
    assert '"stage": "point_location_crop"' in trace_content


@pytest.mark.asyncio
async def test_agent_service_uses_local_perpendicular_overlay_plan_without_draw_llm(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    for offset in (120, 380, 650):
        c = (offset + 90, 220)
        e = (offset + 180, 330)
        b = (offset + 40, 330)
        h = (offset + 120, 420)
        draw.line([c, e], fill="black", width=4)
        draw.line([c, b], fill="black", width=4)
        draw.line([c, h], fill="black", width=4)
    image.save(image_path)

    repository = InMemoryAssetRepository()
    repository.assets["asset-1"] = {
        "asset_id": "asset-1",
        "asset_type": "question_image",
        "storage_backend": "local",
        "object_key": object_key,
        "url": "/assets/uploads/asset-1.png",
        "filename": "asset-1.png",
        "mime_type": "image/png",
        "size_bytes": image_path.stat().st_size,
        "width": 900,
        "height": 600,
        "metadata": {},
    }
    llm = FakePerpendicularOverlayLLM()
    service = AgentService(
        llm_client=llm,
        asset_repository=repository,
        session_repository=FakeSessionRepository(),
        sandbox_service=FakeSandbox(),
        settings=SimpleNamespace(
            asset_storage_path=str(tmp_path),
            asset_base_url="/assets",
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path / "traces"),
            figure_target_crop_vision_enabled=False,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    assert any(event["event"] == "figure_result" for event in events)
    assert llm.point_location_calls == 1
    assert "figure_goal" not in llm.chat_json_calls
    assert "figure_draw" not in llm.chat_json_calls
    assert "figure_revision" not in llm.chat_json_calls
    trace_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "traces").rglob("*.jsonl")
    )
    assert '"scene": "local_overlay_planner"' in trace_content
    assert '"op": "point_on_perpendicular_by_distance"' in trace_content


@pytest.mark.asyncio
async def test_agent_service_renders_structured_geometry_before_legacy_python_figure():
    llm = FakeGeometryLLM()
    session_repo = FakeSessionRepository()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=session_repo,
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-geometry",
            "image_url": "/assets/figures/asset-geometry.png",
        },
    }]
    assert len(sandbox.requests) == 1
    assert "linestyle='--'" in sandbox.requests[0].code
    assert "plt.plot([0],[0])" not in sandbox.requests[0].code
    assert session_repo.context["current_geometry"]["version"] == "1.0"


@pytest.mark.asyncio
async def test_agent_service_falls_back_to_legacy_python_figure_when_structured_has_no_operations():
    llm = FakeLegacyFigureLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-geometry",
            "image_url": "/assets/figures/asset-geometry.png",
        },
    }]
    assert len(sandbox.requests) == 1
    assert "plt.plot([0], [0])" in sandbox.requests[0].code


@pytest.mark.asyncio
async def test_agent_service_uses_figure_agent_when_no_structured_operation_or_legacy_code():
    llm = FakeFigureAgentFallbackLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-geometry",
            "image_url": "/assets/figures/asset-geometry.png",
        },
    }]
    assert "figure_trigger" not in llm.chat_json_calls
    assert "figure_goal" in llm.chat_json_calls
    assert len(sandbox.requests) == 1
    assert "plt.plot([0], [0])" in sandbox.requests[0].code


@pytest.mark.asyncio
async def test_agent_service_does_not_short_circuit_figure_agent_after_structured_candidate():
    llm = FakeStructuredCandidateAndFigureAgentLLM()
    sandbox = FakeSequencedSandbox([
        {"asset_id": "asset-structured", "image_url": "/assets/figures/asset-structured.png"},
        {"asset_id": "asset-agent", "image_url": "/assets/figures/asset-agent.png"},
    ])
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-agent",
            "image_url": "/assets/figures/asset-agent.png",
        },
    }]
    assert "figure_trigger" not in llm.chat_json_calls
    assert "figure_goal" in llm.chat_json_calls
    assert len(sandbox.requests) == 2
    assert "linestyle='--'" in sandbox.requests[0].code
    assert "plt.plot([9], [9])" in sandbox.requests[1].code


@pytest.mark.asyncio
async def test_agent_service_treats_structured_candidate_as_react_observation(tmp_path):
    llm = FakeStructuredCandidateRevisionLLM()
    sandbox = FakeSequencedSandbox([
        {"asset_id": "asset-structured", "image_url": "/assets/figures/asset-structured.png"},
        {"asset_id": "asset-revised", "image_url": "/assets/figures/asset-revised.png"},
    ])
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=FakeSemanticSettings(str(tmp_path)),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-revised",
            "image_url": "/assets/figures/asset-revised.png",
        },
    }]
    assert llm.semantic_calls == 1
    assert llm.revision_calls == 1
    assert len(sandbox.requests) == 2
    assert "linestyle='--'" in sandbox.requests[0].code
    assert "plt.plot([8], [8])" in sandbox.requests[1].code


@pytest.mark.asyncio
async def test_agent_service_figure_agent_falls_back_when_trigger_is_incomplete(tmp_path):
    llm = FakeMalformedTriggerFigureAgentLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=SimpleNamespace(
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path / "traces"),
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert len(figure_events) == 1
    assert "figure_trigger" in llm.chat_json_calls
    assert "figure_goal" in llm.chat_json_calls
    assert len(sandbox.requests) == 1
    trace_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "traces").rglob("*.jsonl")
    )
    assert '"figure_needed": true' in trace_content
    assert '"trigger_source": "fallback_geometry_image"' in trace_content


@pytest.mark.asyncio
async def test_agent_service_figure_agent_writes_minimal_trace(tmp_path):
    llm = FakeFigureAgentFallbackLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=SimpleNamespace(
            agent_trace_enabled=True,
            agent_trace_dir=str(tmp_path),
            asset_storage_path=str(tmp_path),
        ),
    )

    [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    trace_files = list(Path(tmp_path).rglob("*.jsonl"))
    assert len(trace_files) == 1
    content = trace_files[0].read_text(encoding="utf-8")
    assert '"stage": "figure_trigger"' in content
    assert '"stage": "figure_goal"' in content
    assert '"stage": "figure_draw_plan"' in content
    assert '"stage": "figure_draw_code"' in content
    assert '"stage": "figure_execution"' in content
    assert '"stage": "figure_observation"' in content


@pytest.mark.asyncio
async def test_agent_service_figure_agent_revises_code_after_render_error():
    llm = FakeRevisionFigureAgentLLM()
    sandbox = FakeFailOnceSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-revised",
            "image_url": "/assets/figures/asset-revised.png",
        },
    }]
    assert llm.figure_draw_calls == 1
    assert llm.revision_calls == 1
    assert len(sandbox.requests) == 2
    assert "bad draw" in sandbox.requests[0].code
    assert "plt.plot([1], [1])" in sandbox.requests[1].code


@pytest.mark.asyncio
async def test_agent_service_figure_agent_redraws_plan_when_revision_requests_it():
    llm = FakeRedrawPlanFigureAgentLLM()
    sandbox = FakeFailOnceSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-revised",
            "image_url": "/assets/figures/asset-revised.png",
        },
    }]
    assert llm.goal_calls == 2
    assert llm.figure_draw_calls == 2
    assert llm.revision_calls == 1
    assert len(sandbox.requests) == 2
    assert "bad first plan" in sandbox.requests[0].code
    assert "plt.plot([2], [2])" in sandbox.requests[1].code


@pytest.mark.asyncio
async def test_agent_service_figure_agent_uses_semantic_observation_as_soft_revision_signal(tmp_path):
    llm = FakeSemanticRevisionFigureAgentLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
        settings=FakeSemanticSettings(str(tmp_path)),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-geometry",
            "image_url": "/assets/figures/asset-geometry.png",
        },
    }]
    assert llm.semantic_calls == 1
    assert llm.revision_calls == 1
    assert len(sandbox.requests) == 2
    assert "plt.plot([0], [0])" in sandbox.requests[0].code
    assert "plt.plot([3], [3])" in sandbox.requests[1].code


@pytest.mark.asyncio
async def test_agent_service_falls_back_to_legacy_python_figure_when_structured_validation_fails():
    llm = FakeInvalidStructuredWithLegacyFigureLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    validator_events = [
        event for event in events
        if event["event"] == "tool_result" and event["data"]["tool"] == "geometry_validator"
    ]
    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert validator_events
    assert figure_events == [{
        "event": "figure_result",
        "data": {
            "asset_id": "asset-geometry",
            "image_url": "/assets/figures/asset-geometry.png",
        },
    }]
    assert len(sandbox.requests) == 1
    assert "plt.plot([0], [0])" in sandbox.requests[0].code


@pytest.mark.asyncio
async def test_agent_service_renders_structured_perpendicular_auxiliary_line():
    llm = FakePerpendicularGeometryLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert len(figure_events) == 1
    assert len(sandbox.requests) == 1
    assert "'F': (1.0, 0.0)" in sandbox.requests[0].code
    assert "['B', 'F']" in sandbox.requests[0].code


@pytest.mark.asyncio
async def test_agent_service_renders_structured_geometry_with_chained_constructed_point():
    llm = FakeChainedPerpendicularGeometryLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    validator_failures = [
        event for event in events
        if event["event"] == "tool_result" and event["data"]["tool"] == "geometry_validator"
    ]
    assert len(figure_events) == 1
    assert validator_failures == []
    assert len(sandbox.requests) == 1
    assert "'F': (1.0, 0.0)" in sandbox.requests[0].code
    assert "'G':" in sandbox.requests[0].code
    assert "['B', 'F']" in sandbox.requests[0].code
    assert "['C', 'G']" in sandbox.requests[0].code


@pytest.mark.asyncio
async def test_agent_service_renders_structured_cut_length_auxiliary_line():
    llm = FakeCutLengthGeometryLLM()
    sandbox = FakeSandbox()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=sandbox,
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="请解答第（2）问",
            asset_ids=["asset-1"],
        )
    ]

    figure_events = [event for event in events if event["event"] == "figure_result"]
    assert len(figure_events) == 1
    assert len(sandbox.requests) == 1
    assert "'F':" in sandbox.requests[0].code
    assert "['H', 'F']" in sandbox.requests[0].code


@pytest.mark.asyncio
async def test_agent_service_emits_answer_end_before_post_processing():
    llm = FakeGeometryLLM()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        sandbox_service=FakeSandbox(),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    event_names = [event["event"] for event in events]
    last_delta_index = max(
        index for index, event_name in enumerate(event_names) if event_name == "delta"
    )
    assert event_names[last_delta_index + 1] == "answer_end"
    assert event_names.index("answer_end") < event_names.index("figure_result")
    assert event_names.index("figure_result") < event_names.index("message_end")


@pytest.mark.asyncio
async def test_agent_service_figure_result_carries_message_id_before_message_end():
    llm = FakeFigureAgentFallbackLLM()
    message_repo = FakeMessageRepository()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        message_repository=message_repo,
        sandbox_service=FakeSandbox(),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    figure_event = next(event for event in events if event["event"] == "figure_result")
    message_end = next(event for event in events if event["event"] == "message_end")
    assert figure_event["data"]["message_id"] == "assistant-1"
    assert message_end["data"]["message_id"] == "assistant-1"
    assert len([item for item in message_repo.created if item.role == "assistant"]) == 1


@pytest.mark.asyncio
async def test_agent_service_emits_transparent_reflexion_result_before_figure(monkeypatch):
    call_order: list[str] = []

    async def transparent_reflexion_check(*args, **kwargs):
        call_order.append("reflexion")
        return SimpleNamespace(
            content="【反思后文本】\n" + kwargs["content"],
            had_violation=True,
            usage={"total_tokens": 1},
        )

    monkeypatch.setattr("app.agent.service.reflexion_check", transparent_reflexion_check)

    class FigureDrawAwareLLM(FakeFigureAgentFallbackLLM):
        async def chat(self, *, messages, scene, temperature=0.3, response_format=None):
            if scene == "figure_draw":
                joined = "\n".join(str(message["content"]) for message in messages)
                assert "【反思后文本】" in joined
            return await super().chat(
                messages=messages,
                scene=scene,
                temperature=temperature,
                response_format=response_format,
            )

    class OrderSandbox(FakeSandbox):
        async def render_figure(self, request):
            call_order.append("render")
            return await super().render_figure(request)

    llm = FigureDrawAwareLLM()
    message_repo = FakeMessageRepository()
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
        message_repository=message_repo,
        sandbox_service=OrderSandbox(),
        settings=SimpleNamespace(
            asset_storage_path="/tmp",
            pre_figure_reflexion_enabled=True,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    event_names = [event["event"] for event in events]
    assert event_names.index("answer_end") < event_names.index("reflexion_result")
    assert event_names.index("reflexion_result") < event_names.index("figure_result")
    assert event_names[-1] == "message_end"
    assert call_order[0] == "reflexion"
    assert "render" in call_order
    assert call_order.index("reflexion") < call_order.index("render")
    assert "reflexion_patch" not in event_names

    reflexion_event = next(event for event in events if event["event"] == "reflexion_result")
    assert reflexion_event["data"]["message_id"] == "assistant-1"
    assert reflexion_event["data"]["status"] == "corrected"
    assert "【反思后文本】" in reflexion_event["data"]["corrected_content"]
    assert "自检修正" in reflexion_event["data"]["visible_message"]


@pytest.mark.asyncio
async def test_agent_service_reflexion_error_is_visible_and_does_not_block_figure(monkeypatch):
    async def broken_reflexion_check(*args, **kwargs):
        raise RuntimeError("reflexion timeout")

    monkeypatch.setattr("app.agent.service.reflexion_check", broken_reflexion_check)

    message_repo = FakeMessageRepository()
    service = AgentService(
        llm_client=FakeFigureAgentFallbackLLM(),
        session_repository=FakeSessionRepository(),
        message_repository=message_repo,
        sandbox_service=FakeSandbox(),
        settings=SimpleNamespace(
            asset_storage_path="/tmp",
            pre_figure_reflexion_enabled=True,
        ),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="帮我看看这道几何题",
            asset_ids=["asset-1"],
        )
    ]

    event_names = [event["event"] for event in events]
    assert event_names.index("answer_end") < event_names.index("reflexion_result")
    assert event_names.index("reflexion_result") < event_names.index("figure_result")
    assert "reflexion_patch" not in event_names

    reflexion_event = next(event for event in events if event["event"] == "reflexion_result")
    assert reflexion_event["data"]["message_id"] == "assistant-1"
    assert reflexion_event["data"]["status"] == "failed"
    assert "自检未完成" in reflexion_event["data"]["visible_message"]
    assert reflexion_event["data"]["issues"] == ["reflexion_error"]


@pytest.mark.asyncio
async def test_agent_service_forces_question_tools_when_uploaded_image_plan_omits_them(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake image bytes")

    llm = FakeGeometryLLM(planning_tool_calls=[])
    service = AgentService(
        llm_client=llm,
        asset_repository=FakeAssetRepository(object_key=object_key),
        settings=FakeSettings(str(tmp_path)),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="（图片）",
            asset_ids=["asset-1"],
        )
    ]

    event_names = [event["event"] for event in events]
    first_delta_index = event_names.index("delta")
    assert event_names[:first_delta_index] == [
        "message_start",
        "thinking",
        "thinking",
        "tool_result",
        "thinking",
        "tool_result",
        "thinking",
    ]
    assert event_names[-1] == "message_end"
    assert llm.chat_json_calls[:3] == ["planning", "vision", "knowledge"]


@pytest.mark.asyncio
async def test_agent_service_keeps_full_progress_for_text_question():
    llm = FakeGeometryLLM(planning_tool_calls=["process_question", "extract_knowledge"])
    service = AgentService(
        llm_client=llm,
        session_repository=FakeSessionRepository(),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="如图，连接 CF。",
            asset_ids=[],
        )
    ]

    thinking_messages = [
        event["data"]["message"]
        for event in events
        if event["event"] == "thinking"
    ]
    assert thinking_messages == [
        "分析题目中...",
        "识别题目中...",
        "提取知识点中...",
        "生成回复中...",
    ]
    assert llm.chat_json_calls[:3] == ["planning", "question_parse", "knowledge"]


@pytest.mark.asyncio
async def test_agent_service_rolls_back_failed_context_load_before_reading_image(tmp_path):
    object_key = "uploads/asset-1.png"
    image_path = tmp_path / object_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake image bytes")

    llm = FakeGeometryLLM(planning_tool_calls=[])
    session_repo = RecoverableBrokenSessionRepository()
    service = AgentService(
        llm_client=llm,
        asset_repository=FakeAssetRepository(object_key=object_key),
        session_repository=session_repo,
        settings=FakeSettings(str(tmp_path)),
    )

    events = [
        event async for event in service.stream_chat(
            session_id="session-1",
            message="解答一下",
            asset_ids=["asset-1"],
        )
    ]

    event_names = [event["event"] for event in events]
    first_delta_index = event_names.index("delta")
    assert event_names[:first_delta_index] == [
        "message_start",
        "thinking",
        "thinking",
        "tool_result",
        "thinking",
        "tool_result",
        "thinking",
    ]
    assert session_repo.rollback_calls == 1
    assert llm.chat_json_calls[:3] == ["planning", "vision", "knowledge"]
