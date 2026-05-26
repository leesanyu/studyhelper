# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""结构化几何绘图的轻量类型别名和常量。"""

from __future__ import annotations

from typing import Any

GeometryScene = dict[str, Any]
AuxiliaryOperation = dict[str, Any]
ValidationResult = dict[str, Any]

CONSTRUCTION_TYPES = {
    "construct_point_on_ray_with_distance",
    "extend_line",
    "extend_ray",
    "intersection",
    "copy_segment_on_ray",
    "construct_parallel",
    "construct_perpendicular",
    "construct_perpendicular_intersection",
    "midpoint",
}
