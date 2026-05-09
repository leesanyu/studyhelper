# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

import json
from pathlib import Path


def test_question_regression_index_tracks_sprint1_geometry_cases():
    repo_root = Path(__file__).resolve().parents[2]
    index_path = repo_root / "tests" / "questions" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))

    cases = {case["id"]: case for case in payload["cases"]}

    assert "geometry-angle-segment-1" in cases
    assert "geometry-angle-segment-2" in cases
    for case in cases.values():
        image_path = repo_root / "tests" / "questions" / case["file"]
        assert image_path.exists()
        assert case["context_contract"]["image_only_to_node"] == "题目识别"
        assert case["context_contract"]["downstream_input"] == "recognized_text_context"
        assert case["required_metadata"] == [
            "current_question",
            "current_diagram",
            "current_knowledge",
        ]
