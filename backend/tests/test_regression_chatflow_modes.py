# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json
import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.chat import ChatCompletionRequest
from app.services.assets import AssetCreate, InMemoryAssetRepository
from app.services.chat import DifyChatService
from app.services.dify import DifyClient


class FakeRegressionDifyClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def stream_chat(self, query, user, conversation_id, files=None, inputs=None):
        self.calls.append(
            {
                "query": query,
                "user": user,
                "conversation_id": conversation_id,
                "files": files,
                "inputs": inputs,
            }
        )
        yield {"event": "message_start", "data": {"conversation_id": "conv-regression"}}
        yield {"event": "delta", "data": {"text": "mock answer"}}
        yield {
            "event": "message_end",
            "data": {
                "dify_message_id": "msg-regression",
                "subject": "数学",
                "knowledge_points": ["几何"],
            },
        }


def load_question_cases() -> list[dict]:
    repo_root = Path(__file__).resolve().parents[2]
    payload = json.loads((repo_root / "tests" / "questions" / "index.json").read_text())
    return payload["cases"]


@pytest.mark.asyncio
async def test_mock_chatflow_regression_uses_asset_mapping_and_text_context():
    asset_repository = InMemoryAssetRepository()
    await asset_repository.create_asset(
        AssetCreate(
            asset_id="asset-regression",
            asset_type="question_image",
            storage_backend="local",
            object_key="uploads/asset-regression.png",
            url="/assets/uploads/asset-regression.png",
            dify_file_id="dify-file-regression",
            filename="question.png",
            mime_type="image/png",
            size_bytes=128,
            width=640,
            height=480,
        )
    )
    dify_client = FakeRegressionDifyClient()
    service = DifyChatService(dify_client=dify_client, asset_repository=asset_repository)

    for case in load_question_cases():
        for mode in case["modes"]:
            events = [
                event
                async for event in service.stream_chat(
                    ChatCompletionRequest(
                        message=f"{case['id']} {mode}",
                        mode=mode,
                        asset_ids=["asset-regression"],
                        client_user_id="regression-mock",
                        current_question="题目识别后的文本",
                        current_diagram="图形结构文本",
                        current_knowledge={"points": ["几何"]},
                    )
                )
            ]
            assert [event["event"] for event in events] == [
                "message_start",
                "delta",
                "message_end",
            ]

    for call in dify_client.calls:
        assert call["files"] == [
            {
                "type": "image",
                "transfer_method": "local_file",
                "upload_file_id": "dify-file-regression",
            }
        ]
        assert call["inputs"]["mode"] in {"direct_answer", "guided_answer"}


@pytest.mark.asyncio
async def test_live_dify_chatflow_regression_entrypoint():
    if os.getenv("RUN_LIVE_DIFY_REGRESSION") != "1":
        pytest.skip("Set RUN_LIVE_DIFY_REGRESSION=1 to run live Dify regression")

    settings = Settings()
    if settings.dify_api_key == "your-dify-app-api-key":
        pytest.skip("DIFY_API_KEY is required for live Dify regression")

    client = DifyClient(settings.dify_api_url, settings.dify_api_key, timeout=30)
    events = [
        event
        async for event in client.stream_chat(
            query="回归测试：请回复 ok",
            user="regression-live",
            conversation_id=None,
            files=[],
            inputs={"mode": "direct_answer"},
        )
    ]
    assert any(event["event"] in {"delta", "message_end"} for event in events)
