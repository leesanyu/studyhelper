# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""应用配置测试。"""

from app.core.config import Settings


def test_pre_figure_reflexion_is_disabled_by_default():
    """默认关闭前置反思，避免覆盖主解题结果并拖慢辅助线流程。"""
    settings = Settings(_env_file=None)

    assert settings.pre_figure_reflexion_enabled is False
    assert settings.figure_semantic_inspection_enabled is False
    assert settings.figure_trigger_llm_enabled is True
    assert settings.figure_goal_check_llm_enabled is True
    assert settings.figure_target_crop_vision_enabled is False
    assert settings.figure_overlay_revision_enabled is True
    assert settings.figure_code_revision_enabled is True
    assert settings.upload_max_image_dimension == 3000
    assert settings.upload_jpeg_quality == 92
    assert settings.upload_webp_quality == 92


def test_pre_figure_reflexion_can_be_enabled_explicitly():
    """需要时仍可通过配置开关显式启用前置反思。"""
    settings = Settings(
        _env_file=None,
        pre_figure_reflexion_enabled=True,
        figure_semantic_inspection_enabled=True,
        figure_trigger_llm_enabled=False,
        figure_goal_check_llm_enabled=False,
        figure_target_crop_vision_enabled=True,
        figure_overlay_revision_enabled=False,
        figure_code_revision_enabled=False,
    )

    assert settings.pre_figure_reflexion_enabled is True
    assert settings.figure_semantic_inspection_enabled is True
    assert settings.figure_trigger_llm_enabled is False
    assert settings.figure_goal_check_llm_enabled is False
    assert settings.figure_target_crop_vision_enabled is True
    assert settings.figure_overlay_revision_enabled is False
    assert settings.figure_code_revision_enabled is False
