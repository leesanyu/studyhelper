# Sprint 4 Design：几何辅助线绘图 Agent

## 1. 设计目标

Sprint 4 的目标是让几何辅助线图稳定可见，并逐步提高准确性。系统不在代码层实现自动几何证明器，也不试图用规则穷举辅助线构造。代码只提供工具、沙箱、安全边界、状态记录和编排；辅助线选择、绘图计划、绘图代码生成和修正主要交给 LLM。

核心目标：

```text
主解题流程：Plan-and-Solve
辅助线绘图子流程：受限 ReAct
```

主解题流程负责理解题目和输出解答。辅助线绘图子流程负责根据题目、解答和辅助线意图生成图，并通过「渲染 → 观察 → 修正」闭环提高图的可用性。

设计原则：

1. **LLM 是大脑，代码是工具。** 代码不替 LLM 决定辅助线怎么画，只提供可调用工具和安全执行环境。
2. **先跑通，再变准。** 检查和校验用于修正，不用于轻易阻断图的展示。
3. **结构化几何是增强器，不是闸门。** 规则抽取、校验和受控渲染可以优先尝试，但失败后必须回退到 LLM 绘图。
4. **`python:figure` 不再被禁止。** 当 LLM 能直接生成有效 matplotlib 代码时，应允许它调用绘图能力。
5. **失败要回到 LLM。** 执行错误、空白图、辅助线缺失或语义不匹配，都应形成 Observation，交给 LLM 修正，最多重试 1 到 2 次。
6. **展示 best effort。** 除非存在安全问题或完全无法生成图片，否则应向用户展示当前最好版本，并在 trace 中记录不足。
7. **少硬化调度。** 除安全、资源和循环上限外，代码不应把辅助线策略、绘图路径和修正判断写死；能由 LLM 根据上下文判断的部分，优先通过 Prompt、Observation 和工具契约交给 LLM。
8. **限制必须有回退。** 新增校验或限制时，必须同时定义失败后的可见回退路径，不能让一个低置信度判断直接导致无图。
9. **优先在原图上叠加。** 对有题图的几何题，优先截取目标几何图并在裁剪图上叠加辅助线；重新绘制示意图只作为无法定位原图时的兜底。

## 2. 总体架构

### 2.1 主流程：Plan-and-Solve

主流程沿用当前 Agent 架构：

```text
message_start
→ thinking(planning)
→ process_question / extract_knowledge
→ thinking(solving)
→ delta
→ answer_end
→ 透明自检结果（可选，输出给用户）
→ Figure Agent（可选）
→ figure_result（可选，多次尝试后取最佳）
→ message_end
```

主流程职责：

1. 调用 planning LLM 判断本轮意图和工具需求。
2. 调用 `process_question` 识别题目、题图、OCR 和图形描述。
3. 调用 `extract_knowledge` 提取知识点。
4. 调用 solving LLM 输出文字解答。
5. 文字解答先流式给用户，再运行透明自检，并把自检结果输出给用户。
6. 调用轻量 post-solve 判断，决定是否启动 Figure Agent。

主流程不负责：

- 由代码决定辅助线方案。
- 用规则强行解释所有辅助线构造。
- 因结构化几何失败而放弃绘图。

### 2.1.1 Figure Agent 触发契约

Figure Agent 是否启动不由代码关键词硬判。Solve 阶段或 post-solve LLM 优先输出一个轻量绘图意图对象；若该对象缺失或格式不完整，代码应把完整题目和解答交给 Figure Agent 继续判断，而不是终止绘图流程。

```json
{
  "figure_needed": true,
  "reason": "解答使用了辅助线证明几何结论",
  "auxiliary_intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
  "confidence": 0.82,
  "existing_python_figure": ""
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `figure_needed` | LLM 判断是否需要绘图。几何证明、辅助线、关键构造和题图解释通常为 `true` |
| `reason` | 触发原因，写入 trace，便于复盘 |
| `auxiliary_intent` | 绘图目标。可以来自 `【辅助线】`，也可以由 LLM 从完整解答中总结 |
| `confidence` | 判断置信度，只影响 warning，不作为硬阻断 |
| `existing_python_figure` | Solve 阶段若已经输出 `python:figure`，这里保留代码块内容；有题图时不压过 overlay-first，只作为无法裁剪、无法定位或 overlay 失败后的候选 |

兜底规则：

1. 若 `figure_needed=true`，无论结构化抽取是否成功，都启动 Figure Agent。
2. 若 `figure_needed=false`，但 Solve 输出包含 `python:figure`，仍尝试执行该代码。
3. 若 post-solve 判断失败，但本轮有图片题图且解答包含几何点线角描述，代码可启动 Figure Agent fallback，并在 trace 中标记 `trigger_source="fallback"`。
4. 若 `auxiliary_intent` 为空，Figure Agent 仍可根据题目和完整解答生成示意图，但必须记录 warning：`auxiliary_intent_missing`。
5. 若轻量绘图意图对象缺失字段，缺失字段写入 warning；Figure Agent 使用现有上下文继续执行。
6. 触发逻辑不能因为关键词未命中、结构化结果为空、意图对象缺失或置信度偏低而直接放弃绘图。

### 2.2 Plan-and-Solve 与 ReAct 的边界

Sprint 4 不把主 Agent 改造成全局 ReAct。主解题流程仍然是一次规划、按计划执行工具、再生成答案的 Plan-and-Solve 模式：

```text
Plan：判断意图和需要的工具
Tool：识别题目、提取知识点、整理视觉观察
Solve：输出文字解题和辅助线意图
```

ReAct 只进入辅助线绘图子流程，并且只围绕「画图」这一个目标循环：

```text
Thought：根据题目和解答规划图怎么画
Action：调用 render_figure / inspect_image 工具
Observation：读取执行错误、图片质量和语义差距
Revision：修正绘图代码后再试
```

这样做的原因是：主解题流程需要稳定、可追踪、低延迟；辅助线绘图则天然开放，适合让 LLM 根据渲染结果反复修正。代码只限制循环次数、工具集合和 sandbox 安全边界，不用规则替代 LLM 的绘图判断。

### 2.2.1 透明自检与后置反思边界

Sprint 4 不再保留后置反思路径。反思只允许出现在文字解题之后、Figure Agent 之前，并且必须对用户透明：

1. Solve 阶段的文字答案继续实时流式输出，不能因为等待反思而长时间无响应。
2. 反思 LLM 的输出必须作为自检结果发给用户，不能只在后台静默修改上下文。
3. 若自检发现原答案存在问题，应明确指出问题，并给出修正建议或修正版；用户看到原答案和自检结果后可以自行判断。
4. Figure Agent 使用「原答案 + 自检结果」作为绘图上下文；若存在修正版，优先按修正版生成辅助线图。
5. 若自检超时、报错或给出不可靠结论，应向用户输出「自检未完成 / 未通过」的可读原因；该状态作为 Figure Agent 的 Observation，不作为默认硬阻断。
6. 反思不是绘图 ReAct 的替代品。绘图后的观察、修正、重画和 best effort 仍由 Figure Agent ReAct 负责。

配置上只保留是否启用透明自检的开关，例如 `pre_figure_reflexion_enabled`；不再提供「后置反思」位置开关。

### 2.3 绘图子流程：Figure Agent ReAct

Figure Agent 是一个受限 ReAct 子流程，只负责生成和修正辅助线图。

```text
Goal Check
→ Target Diagram Crop / Point Locate（有题图时优先）
→ Draw Plan
→ Action: render_overlay / render_figure
→ Observation: execution / image_quality / semantic_check
→ Revision（可选）
→ Action: render_overlay / render_figure
→ Observation
→ select best effort
→ figure_result
```

Figure Agent 的 ReAct 循环按渲染 attempt 计数，Goal Check 不计入 attempt。默认最多 2 次渲染 attempt；仅当第 2 次仍是明确代码错误、且尚未命中安全策略时，允许第 3 次修正 attempt。

Figure Agent 的输入包含原始文字答案和透明自检结果。它可以采纳自检给出的修正版或风险提示，但不负责重新解题；如果自检明确指出解答不可靠，Figure Agent 仍可 best effort 生成辅助线图，但必须把风险提示挂到同一消息，除非没有任何可绘图目标或命中安全限制。

- Goal Check：整理绘图目标，得到 `expected_auxiliary`、`layout_hint` 和样式目标。
- 第 1 轮：基于绘图目标生成初版绘图代码。
- 第 2 轮：若 sandbox 失败、空白图或语义自检低分，则修正一次。
- 第 3 轮：仅在第 2 轮仍因明确代码错误失败时使用；否则展示 best effort。

### 2.3.1 原图 Overlay 优先路径

Demo 验证表明，直接让 LLM 根据题意重新创造几何图，位置、比例和辅助线方向都容易漂移；而「目标图裁剪 + 点位定位 + 原图叠加」能保留原题图结构，辅助线更容易和文字答案一致。因此有题图的几何题采用 overlay-first：

```text
Asset：读取原始题图
→ Target Diagram Crop：定位当前小问对应的几何子图，例如「图 2」
→ Point Location Crop：优先用本地版面裁剪生成稳定点位定位图，VLM 裁剪只作为兜底
→ Point Locate：Vision LLM 在点位定位裁剪图坐标系定位 A/B/C/D/E/H 等点
→ Point Snap：本地像素工具把 VLM 粗坐标吸附到附近线段端点、交点或折点
→ Auxiliary Extract：从 Solve 原文提取辅助线文本，保留原句
→ Goal Check：LLM 归一化辅助线目标，保留有向延长线语义
→ Draw Plan：LLM 输出 overlay 操作计划
→ Render Overlay：在裁剪图上绘制辅助线，输出放大后的目标图
→ Vision Observation：检查辅助线是否和文字一致、方向是否相反、是否遮挡
→ Revision：只修正绘图计划或渲染代码，不改写证明
```

该路径的关键约束：

1. **目标图裁剪优先于整页叠加。** 前端展示应优先使用裁剪后的几何图，避免整页题干压缩导致辅助线不可读。
2. **点位定位使用稳定裁剪图坐标系。** Point Locate 的输入优先来自本地版面裁剪得到的稳定 `point_location_crop`，而不是 VLM 先验裁剪框。Vision LLM 必须返回该裁剪图像素坐标，再由工具直接在同一裁剪图上渲染。
3. **点位吸附只做像素修正。** VLM 负责识别点名和粗坐标；Point Snap 工具只在局部窗口内寻找线段端点、交点或折点，并把坐标吸附过去。它不改变点名、辅助线语义或构造策略；吸附失败时保留 VLM 原坐标并写入 warning，不能阻断绘图。
4. **辅助线原文必须进入 trace。** 例如 `延长 AE 至点 F，使 EF = AE，连接 CF、BF。` 必须作为 Figure Agent 的主输入之一，而不是只依赖正则抽取结果。
5. **延长线必须有方向。** `ray: "AE"` 表示从 `A` 经 `E` 往 `E` 外侧延长；`ray: "EA"` 表示从 `E` 经 `A` 往 `A` 外侧延长。代码不得把 `AE` 和 `EA` 当成无向线段。
6. **overlay 操作计划优先于自由重画代码。** LLM 优先输出结构化 overlay plan；只有无法裁剪、无法定位点位或 overlay plan 不足以表达目标时，才 fallback 到 `python:figure` 示意图。
7. **图像质量优先服务可读性。** 辅助线使用细虚线或半透明线，尽量不遮挡原图字母和已有线段；必要时输出 2 倍裁剪图。
8. **点位 Prompt 保持最小化。** 点位定位阶段只给目标裁剪图、裁剪图尺寸、待定位点和必要题目信息；不要注入完整解答、Goal Check、网格图或语义检查要求，避免 Vision LLM 把证明文本当成定位依据。

### 2.3.2 模型路由约束

Demo 验证还暴露出模型路由问题：不能用视觉模型替代文字解题模型评估 Solve 质量。正式流程必须按场景选择模型：

| 场景 | 推荐模型 | 说明 |
|------|----------|------|
| `solving` | `qwen3.6-plus` | 文字解题、辅助线原文生成，必须和生产配置一致 |
| `vision` | `qwen-vl-max-latest` | 题图识别、目标图定位、点位定位 |
| `figure_trigger` | `qwen3.6-plus` | 无明确辅助线文本时判断是否需要启动 Figure Agent |
| `figure_goal` | `qwen3.6-plus` | 将辅助线文本整理成绘图目标；可由本地轻量 Goal 兜底 |
| `figure_draw` | `qwen3.6-plus` | 根据辅助线原文和点位生成 overlay plan |
| `figure_revision` | `qwen3.6-plus` | 根据 Observation 修正 overlay plan 或绘图代码 |
| `figure_semantic_inspection` | `qwen-vl-max-latest` | 判断最终图是否和辅助线文字一致 |

Trace 必须记录每个阶段的 `scene`、`model` 和 usage。若 demo、测试或线上调试临时替换模型，结论必须标注模型差异，不能把非生产模型输出当作生产质量依据。

所有需要 LLM/VLM 参与的反思、检查、裁剪定位和修正节点都必须有配置开关。关闭开关时，编排层使用本地轻量回退或直接保留 best effort 结果，并把跳过原因写入 trace；关闭检查不能变成新的阻断条件。

| 开关 | 默认值 | 关闭后的行为 |
|------|--------|--------------|
| `pre_figure_reflexion_enabled` | `False` | 不运行透明自检，Figure Agent 直接基于 Solve 输出绘图 |
| `figure_semantic_inspection_enabled` | `False` | 不调用 VLM 语义复查，只保留程序级 Observation |
| `figure_trigger_llm_enabled` | `True` | 无辅助线文本时使用本地几何兜底触发；有辅助线文本时始终跳过 Trigger LLM |
| `figure_goal_check_llm_enabled` | `True` | 使用辅助线原文、本地图号推断和规则解析生成轻量 Goal |
| `figure_target_crop_vision_enabled` | `False` | 优先使用本地版面裁剪；找不到稳定裁剪时再 fallback 到后续路径 |
| `figure_overlay_revision_enabled` | `True` | Overlay 出现 Observation 时不调用 LLM 修正，直接展示已有 best effort 图 |
| `figure_code_revision_enabled` | `True` | Python 绘图代码失败或语义复查要求修正时，不调用 LLM 修正代码 |

### 2.4 代码和 LLM 的职责分工

| 角色 | 职责 |
|------|------|
| Planning LLM | 决定是否调用题目识别、知识点提取、绘图子流程 |
| Solving LLM | 输出解答、辅助线说明、必要的绘图意图 |
| Reflexion LLM | 对已输出答案做透明自检，指出问题、修正建议和绘图风险 |
| Figure LLM | 从文字解答整理 overlay 绘图计划；必要时生成 matplotlib 代码；根据 Observation 修正计划或代码 |
| Vision LLM | 定位目标子图和点位；对渲染图进行语义自检，判断图是否符合辅助线目标 |
| 后端编排代码 | 组织上下文、调用 LLM、调用工具、控制重试次数、保存 trace |
| Target Crop / Point Locate / Point Snap 工具 | 截取目标几何图、保存裁剪元数据、优先生成稳定 `point_location_crop`，把点位坐标统一到裁剪图坐标系，并把 VLM 粗坐标吸附到附近几何线段端点、交点或折点 |
| Overlay Renderer | 按 overlay plan 在裁剪图上绘制辅助线，生成用户可见图片 |
| Sandbox | 兜底执行 Python 绘图代码，生成示意图图片资产 |
| 程序检查器 | 检查图片是否生成、是否空白、尺寸是否正常 |
| 前端 | 被动展示 `delta`、`figure_result`、warning 和最终状态 |

## 3. Figure Agent 输入输出

### 3.1 输入上下文

Figure Agent 必须拿到完整上下文，而不是只拿一句辅助线。

```json
{
  "session_id": "会话 ID",
  "message_id": "消息 ID",
  "asset_ids": ["题图资产 ID"],
  "question_text": "题干原文",
  "diagram_description": "题图描述",
  "visual_observation": {
    "points": [],
    "drawn_segments": [],
    "marks": [],
    "uncertain": []
  },
  "target_diagram": {
    "label": "图2",
    "crop_asset_id": "asset-crop-xxx",
    "crop_box": [1260, 823, 2090, 1655],
    "coordinate_space": "crop_pixels",
    "display_scale": 2
  },
  "point_location_crop": {
    "source": "layout_component",
    "crop_box": [1260, 823, 2090, 1655],
    "coordinate_space": "crop_pixels",
    "width": 830,
    "height": 832
  },
  "localized_points": {
    "A": {"x": 615, "y": 394, "confidence": 0.95},
    "B": {"x": 170, "y": 394, "confidence": 0.95}
  },
  "point_snap": {
    "source": "local_cv",
    "raw_points": {
      "A": {"x": 620, "y": 380, "confidence": 0.95}
    },
    "adjustments": {
      "A": {"snapped": true, "x": 615, "y": 394, "delta": 14.9, "snap_confidence": 0.87}
    },
    "warnings": []
  },
  "geometry_scene_candidate": {},
  "solve_content": "完整文字解答",
  "reflexion_result": {
    "status": "passed | corrected | unreliable | failed",
    "visible_message": "已展示给用户的自检结果",
    "corrected_content": "如有修正版，填写修正后的解答；否则为空",
    "issues": ["发现的问题或风险点"],
    "figure_guidance": "给 Figure Agent 的绘图风险提示"
  },
  "auxiliary_text": "解答原文中的辅助线句，例如：延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
  "auxiliary_intent": "LLM 归一化后的辅助线意图",
  "existing_python_figure": "Solve 阶段已经输出的 python:figure 代码，可为空",
  "user_constraints": "七年级、全等知识、不能使用勾股定理等",
  "trigger": {
    "source": "post_solve_llm",
    "figure_needed": true,
    "reason": "解答使用了辅助线",
    "confidence": 0.82
  },
  "style_requirements": {
    "original_lines": "black solid",
    "auxiliary_lines": "red dashed",
    "labels": "readable"
  }
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `session_id` | 会话 ID，用于 trace 和图片归属 |
| `message_id` | 当前 AI 消息 ID，后置 `figure_result` 必须挂回该消息 |
| `asset_ids` | 本轮题图资产，用于 trace 和可选视觉检查 |
| `question_text` | 题目文本，是绘图目标的主上下文 |
| `diagram_description` | 题图文字描述，作为布局和元素参考 |
| `visual_observation` | 点、线、标记、OCR 和不确定项 |
| `target_diagram` | 当前小问对应的目标子图，包括标签、裁剪资产、裁剪框、坐标系和展示倍率 |
| `point_location_crop` | Point Locate 实际使用的稳定裁剪图。优先来源为本地版面裁剪；VLM 裁剪只在本地裁剪不可用时兜底 |
| `localized_points` | Point Snap 后的最终点位，使用裁剪图像素坐标；若吸附失败则等于 Vision LLM 原坐标 |
| `point_snap` | 本地像素吸附结果，包括 VLM 原坐标、吸附后的点位、偏移量、置信度和 warning |
| `geometry_scene_candidate` | 可选结构化几何事实，供 LLM 参考，不作为硬闸门 |
| `solve_content` | 已输出给用户的解答文本 |
| `reflexion_result` | 已输出给用户的透明自检结果；Figure Agent 可据此修正绘图目标或降级提示 |
| `auxiliary_text` | Solve 原文中的辅助线句，必须写入 trace；优先作为 Goal Check 输入 |
| `auxiliary_intent` | 从解答中提取的辅助线意图；可由 LLM 提取，不限于规则抽取 |
| `existing_python_figure` | Solve 阶段已有绘图代码时保留为 fallback 候选；有题图且 overlay 条件满足时，优先走目标图裁剪和 overlay plan |
| `user_constraints` | 用户对知识点、年级、证明方法的约束 |
| `trigger` | Figure Agent 触发来源、原因和置信度 |
| `style_requirements` | 图形展示样式约束 |

### 3.2 Goal Check 输出

Draw Plan 之前先做一次轻量 Goal Check。它不是代码校验，也不是几何证明器；它由 LLM 把题目、解答和辅助线意图整理成稳定的绘图目标，供后续 Observation 对照。

```json
{
  "goal_status": "ready",
  "render_mode": "overlay_on_crop",
  "target_diagram": "图2",
  "coordinate_space": "crop_pixels",
  "normalized_auxiliary_intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
  "expected_auxiliary": [
    "F lies on the ray from A through E",
    "EF equals AE",
    "CF is connected",
    "BF is connected"
  ],
  "original_figure_elements": [
    "A/B/C/D/E/H labels",
    "segments CA, CB, CE, EH, CH, BH"
  ],
  "layout_hint": {
    "type": "overlay_on_crop",
    "preserve_collinear": ["A-E-F", "E-A-H", "C-D-H"],
    "directed_rays": [{"ray": "AE", "meaning": "从 A 经 E 向 E 外侧延长"}],
    "show_perpendicular": ["CA-CB", "CE-EA"]
  },
  "style_requirements": {
    "original_lines": "black solid",
    "auxiliary_lines": "purple dashed",
    "labels": "readable"
  },
  "warnings": []
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `goal_status` | `ready` / `needs_inference` / `conflict`。`conflict` 作为目标冲突 Observation 交给 Draw Plan 或 Revision LLM，不由代码改写证明 |
| `render_mode` | 优先为 `overlay_on_crop`；无法裁剪或定位时 fallback 到 `schematic_python_figure` |
| `target_diagram` | 当前要渲染的子图标签，例如 `图2` |
| `coordinate_space` | 后续 Draw Plan 使用的坐标系，优先为裁剪图像素坐标 |
| `normalized_auxiliary_intent` | LLM 归一化后的绘图目标，作为 Draw Plan 主目标 |
| `expected_auxiliary` | 后续 Vision 检查和 Revision 的稳定参照 |
| `original_figure_elements` | 原图应保留的关键点线，不要求完全复刻原题图 |
| `layout_hint` | 共线、垂直、位置关系等布局提示，帮助图朝正确方向收敛 |
| `style_requirements` | 样式目标，可覆盖默认样式 |
| `warnings` | 目标不完整、题图信息不足、布局只能示意等提示 |

Goal Check 规则：

1. `expected_auxiliary` 允许来自完整解答总结，不要求代码规则抽取成功。
2. `goal_status=needs_inference` 时仍可继续 Draw Plan，但要写入 warning。
3. `goal_status=conflict` 时，Figure Agent 先把冲突作为 Observation 交给 Draw Plan LLM 重新整理绘图目标；若已经进入 Revision，则由 Revision 返回 `need_redraw_plan` 重新进入目标整理。代码不得直接选择辅助线策略。
4. Goal Check 输出写入 trace，供每次 Observation 对照。
5. Goal Check 必须显式保留有向延长线。`AE` 和 `EA` 代表相反射线，不能被归一化成无向线段。

### 3.3 输出契约

有题图且已完成目标图裁剪和点位定位时，Figure LLM 优先输出 overlay plan，而不是自由 `python:figure`。overlay plan 是 Figure Agent 的主契约，便于保留原图、控制延长线方向并减少重画误差。

```json
{
  "plan_type": "overlay_on_crop",
  "coordinate_space": "crop_pixels",
  "intent": "延长 AE 至 F，使 EF = AE，连接 CF、BF。",
  "constructions": [
    {
      "op": "point_on_segment_by_distance",
      "point": "F",
      "ray": "AE",
      "from": "A",
      "distance": "2*AE",
      "role": "construction"
    },
    {
      "op": "connect_points",
      "points": ["C", "F"],
      "role": "construction"
    },
    {
      "op": "connect_points",
      "points": ["B", "F"],
      "role": "construction"
    }
  ],
  "warnings": []
}
```

overlay plan 规则：

1. `plan_type=overlay_on_crop` 表示在目标子图裁剪图上绘制，前端优先展示裁剪后的图片。
2. 所有点坐标默认来自 `localized_points`；新点由绘图工具按计划计算。
3. `ray` 是有向射线：`AE` 表示从 `A` 经 `E` 向外延长，`EA` 表示从 `E` 经 `A` 向外延长。
4. `distance` 支持 `AE`、`2*AE`、`AH` 等长度表达；工具只负责按点位计算位置，不推导辅助线策略。
5. 辅助线默认使用细虚线或半透明线，不遮挡原图主体；新点标签只标新增点，原图已有标签尽量不重复覆盖。
6. 无法解析某个 operation 时，将失败项写入 Observation，交给 Revision LLM 修正，不直接终止 Figure Agent。

当没有题图、无法定位目标子图、无法定位必要点位，或 overlay plan 无法表达目标时，Figure LLM fallback 到 `python:figure` 代码块：

```markdown
```python:figure
# matplotlib code
```
```

`python:figure` 代码要求：

1. 使用 matplotlib 绘图。
2. 不使用网络请求。
3. 不读写任意文件，不调用 `open()`、`os`、`subprocess`。
4. 不调用 `plt.savefig()`，由 sandbox 统一保存。
5. 隐藏坐标轴。
6. 原图线段使用黑色实线，辅助线使用红色虚线。
7. 点标签必须可读。

代码安全由 sandbox 执行层负责，不依赖 LLM 自觉遵守。

解析规则：

1. 若 `render_mode=overlay_on_crop`，优先解析 overlay plan。
2. 若 overlay plan 缺失或无法解析，将缺失项作为 Observation 交给 Revision LLM 修正。
3. 若 Goal Check 判断需要示意重画，或没有可用裁剪图，才解析 `python:figure`。
4. 若输出包含标准 `python:figure` 代码块，直接提取该代码块。
5. 若输出夹带解释文字但包含可识别的 Python 绘图代码，代码层做 best-effort 提取，并记录 warning。
6. 若输出不是标准代码块但包含普通 Python 代码块，可尝试作为绘图代码执行。
7. 若无法提取任何可执行代码或 overlay plan，将「未提取到绘图计划」作为 Observation 交给 Revision / Draw Plan 重新生成，不直接终止 Figure Agent。

## 4. Observation 设计

Revision 能否有效，取决于 Observation 是否可行动。Observation 不能只写「图不对」，必须拆成执行结果、图像质量和语义差距。

### 4.1 程序级 Observation

程序检查由代码完成，负责低层事实。

```json
{
  "execution": {
    "ok": true,
    "error": "",
    "timeout": false
  },
  "image_quality": {
    "ok": true,
    "non_blank": true,
    "width": 800,
    "height": 600,
    "non_background_ratio": 0.08
  }
}
```

渲染失败 Observation 条件：

| 条件 | 处理 |
|------|------|
| Python 语法错误 | 将 stderr 交给 Revision LLM 修正 |
| sandbox 超时 | 要求 LLM 简化代码后重试 |
| 未产出 PNG | 要求 LLM 修正代码后重试 |
| 图片为空白 | 要求 LLM 检查坐标和绘图调用后重试 |
| 安全策略命中 | 当前 attempt 不展示、不复用代码；可以要求 LLM 重新生成安全代码 |

除安全策略命中外，上述条件都不表示流程终止；它们只是进入 Revision 或重新 Draw Plan 的 Observation 来源。

安全策略说明：

1. 命中安全策略的 attempt 永远不能作为 best effort 展示。
2. 危险代码不进入 Revision 的「保留上一版代码」路径，只能让 LLM 基于绘图目标重新生成安全代码。
3. 返回给用户的失败信息只说明「绘图代码未通过安全检查」，不暴露危险代码细节。
4. 安全失败仍写入 trace，但 trace 中应区分 `security_blocked=true`，便于后续审计。
5. 若连续两次命中安全策略，终止 Figure Agent，发送非致命 `figure_agent` 失败事件。

### 4.2 视觉语义 Observation

视觉语义检查由 Vision LLM 完成，输入为题目、辅助线目标、绘图代码和渲染图片。

目标输出：

```json
{
  "semantic_check": {
    "has_diagram": true,
    "shows_original_figure": true,
    "shows_auxiliary_lines": true,
    "auxiliary_matches_text": false,
    "expected_auxiliary": [
      "F lies on the ray from A through E",
      "CF is connected",
      "BF is connected"
    ],
    "observed_auxiliary": [
      "BF"
    ],
    "missing": [
      "CF is connected"
    ],
    "wrong": [
      "F is placed on ray EA instead of ray AE"
    ],
    "confidence": 0.62
  },
  "revision_guidance": {
    "keep": [
      "Original labels A/B/C/D/E/H are visible",
      "BF is drawn as an auxiliary line"
    ],
    "missing": [
      "CF is connected"
    ],
    "wrong": [
      "F is placed on the wrong extension direction"
    ],
    "style_issues": [
      "Auxiliary line is too thick"
    ],
    "next_action": "revise_code"
  },
  "suggested_fix": [
    "Use ray AE, meaning from A through E and beyond E.",
    "Recompute F on the AE ray.",
    "Draw CF and BF as thin dashed auxiliary lines."
  ]
}
```

Vision LLM 检查重点：

1. 图是否包含题目核心点。
2. 有题图时，是否使用目标子图裁剪图，而不是把整页题干压缩展示。
3. 原图骨架是否大体存在。
4. 辅助线是否按解答文字画出。
5. 新点是否和证明中的点一致。
6. 垂线、延长线、截长点是否明显偏离目标。
7. 有向延长线方向是否正确，尤其 `AE` 和 `EA` 是否被画反。
8. 标签是否可读。
9. 辅助线是否足够突出且没有遮挡原图关键字母。

Vision LLM 不负责：

- 完整证明几何结论是否成立。
- 判断辅助线策略是否唯一或最优。
- 因图不完美而阻断最终展示。

### 4.2.1 Revision Guidance

语义 Observation 必须尽量生成可执行的 Revision Guidance，避免 Revision LLM 重画时丢掉上一轮正确部分。

```json
{
  "keep": [],
  "missing": [],
  "wrong": [],
  "style_issues": [],
  "next_action": "revise_code"
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `keep` | 上一轮已经正确表达的点、线、标签和辅助线，Revision 应保留 |
| `missing` | 相对 Goal Check 的 `expected_auxiliary` 缺失项 |
| `wrong` | 明显画错、位置冲突、辅助线与目标相反的部分 |
| `style_issues` | 标签重叠、颜色不明显、虚实线错误等展示问题 |
| `next_action` | `revise_code` / `redraw_plan` / `accept_best_effort` |

`next_action` 规则：

1. `revise_code`：目标清楚，代码或图形表达需要修正。
2. `redraw_plan`：绘图目标缺失、互相矛盾，或上一轮代码结构已经难以局部修补；该动作只能让 LLM 重新整理绘图目标或重新生成绘图代码。
3. `accept_best_effort`：图片安全、非空、主要辅助线可见，剩余问题只影响示意精度；代码必须选择当前最佳 attempt 并输出 `figure_result`，不能把它当作无图失败。
4. 代码只根据 `next_action` 控制下一步工具调用，不自行推导辅助线策略。

### 4.3 综合评分

每次绘图尝试都生成一个分数，用于选择 best effort。

```text
base_score =
  execution_ok(0/1) * 40
  + non_blank(0/1) * 25
  + image_size_ok(0/1) * 10
  + has_visible_lines(0/1) * 10

semantic_score =
  labels_readable(0/1) * 5
  + auxiliary_matches(0.0-1.0) * 10

score = base_score + semantic_score
```

字段来源：

| 字段 | 来源 | 说明 |
|------|------|------|
| `execution_ok` | sandbox 执行结果 | Python 成功执行且未命中安全策略 |
| `non_blank` | `inspect_image_basic` | 图片非空白，非背景像素比例超过最低阈值 |
| `image_size_ok` | `inspect_image_basic` | 图片宽高满足最小展示尺寸 |
| `has_visible_lines` | `inspect_image_basic` | 图片中存在可见线条或标记 |
| `labels_readable` | Vision LLM，可选 | 语义检查关闭时按 `0` 计，不阻断展示 |
| `auxiliary_matches` | Vision LLM，可选 | 取值 `0.0-1.0`；语义检查关闭时按 `0` 计 |

语义检查关闭时，最高分为 85。只要程序级检查通过，图片可以进入展示或 best effort；不能因为没有 Vision LLM 分数而判为不可展示。

建议阈值：

| 分数 | 处理 |
|------|------|
| `>= 80` | 直接展示 |
| `60-79` | 展示，同时记录 warning |
| `< 60` | 若还有重试次数，进入 Revision；否则有安全非空图片时展示 best effort |
| `0` | 只有没有任何可展示图片时，才显示失败原因 |

展示底线：

1. `security_blocked=true` 的 attempt 不展示。
2. `execution_ok=false` 且无图片资产时不展示。
3. `execution_ok=true`、`non_blank=true`、`image_size_ok=true` 时，即使语义分低，也可以作为 best effort 展示。
4. 若所有 attempt 都低于 60，但存在安全、非空、尺寸正常的图片，展示最高分图片并发送 warning。
5. 只有所有 attempt 都无可展示图片时，才发送失败原因。

## 5. Revision LLM

### 5.1 Revision 输入

Revision LLM 必须同时看到目标、上一次代码和差距清单。

```json
{
  "goal": {
    "question_text": "题干",
    "auxiliary_intent": "辅助线目标",
    "style_requirements": {}
  },
  "previous_attempt": {
    "code": "上一版 python:figure 代码",
    "image_url": "/assets/figures/asset-xxx.png",
    "execution": {},
    "semantic_check": {}
  },
  "observation": {
    "keep": [],
    "missing": [],
    "wrong": [],
    "style_issues": [],
    "next_action": "revise_code",
    "suggested_fix": []
  }
}
```

### 5.2 Revision Prompt 约束

Revision LLM 的任务不是重新解题，而是修正绘图代码。若发现辅助线意图本身缺失、矛盾或无法落图，Revision 统一返回 `need_redraw_plan`，由 Figure Agent 回到 Goal Check / Draw Plan 重新整理绘图目标；代码不得在该分支中自行改写证明。`intent_conflict` 只能作为 `reason` 或 warning，不作为独立状态。

```text
你是几何绘图修正器。
你不会重新解题。
你只根据 Observation 修改上一版 matplotlib 代码。

必须保留：
- 原图主要点和已知线；
- 已正确绘制的辅助线；
- Observation.keep 中列出的正确部分；
- 坐标轴隐藏；
- 红色虚线表示辅助线；
- 黑色实线表示原图。

必须修复：
- Observation.missing 中列出的项目；
- Observation.wrong 中列出的项目；
- Observation.style_issues 中列出的展示问题；
- sandbox stderr 中指出的代码错误。

输出：
正常修图时只输出一个 python:figure 代码块，不解释。
若辅助线意图缺失、矛盾或无法落图，只输出下方特殊回退 JSON。
```

特殊回退：

```json
{
  "status": "need_redraw_plan",
  "reason": "intent_conflict: 辅助线目标缺失或互相矛盾",
  "suggested_auxiliary_intent": "根据完整解答重新总结的绘图目标"
}
```

该回退只用于重建绘图目标，不用于改写文字解答。

### 5.3 Revision 循环终止条件

终止条件：

1. sandbox 执行成功且综合评分达到展示阈值。
2. 达到最大重试次数。
3. 连续两次生成相同错误。
4. 连续两次命中安全策略。

终止后：

- 若存在可展示图片，发送 `figure_result`。
- 若图片有 warning，同时发送 `tool_result(tool="figure_observation")`。
- 若完全无法生成图片，发送非致命 `tool_result(tool="figure_agent")`，文字解题不回滚。

## 6. 结构化几何模块的新定位

现有结构化模块保留，但降级为可选增强能力。

| 模块 | 新定位 |
|------|--------|
| `geometry_normalizer` | 给 Figure LLM 提供结构化参考，不作为唯一真相源 |
| `auxiliary_extractor` | 可用于提取候选辅助线目标，但失败不阻断绘图 |
| `geometry_validator` | 输出 warning 和候选问题，不决定是否最终展示 |
| `geometry_renderer` | 可作为首轮快速渲染尝试，不再替代 LLM 绘图 |

旧规则需要调整：

1. 不再禁止 `python:figure`。
2. 不再要求有 `GeometrySceneCandidate` 时只能走结构化渲染。
3. 不再将校验失败视为「不画图」的理由。
4. 结构化抽取为空时，转入 Figure LLM 生成绘图代码。
5. 结构化渲染失败时，把失败原因作为 Observation 交给 Revision LLM。

## 7. Agent 和工具接口

### 7.1 Figure Agent 编排接口

建议新增内部方法：

```python
async def run_figure_agent(
    *,
    session_id: str,
    message_id: str,
    asset_ids: list[str],
    question_text: str,
    diagram_description: str,
    visual_observation: dict | None,
    target_diagram: dict | None,
    localized_points: dict | None,
    geometry_scene_candidate: dict | None,
    solve_content: str,
    reflexion_result: dict | None,
    auxiliary_text: str | None,
    auxiliary_intent: str | None,
    existing_python_figure: str | None,
    user_constraints: str,
    style_requirements: dict,
    trigger: dict,
    config: FigureAgentConfig,
) -> FigureAgentResult:
    ...
```

配置：

```python
@dataclass
class FigureAgentConfig:
    max_attempts: int = 2
    allow_third_attempt_on_code_error: bool = True
    overlay_on_crop_enabled: bool = True
    crop_display_scale: int = 2
    semantic_inspection_enabled: bool = False
    trigger_llm_enabled: bool = True
    goal_check_llm_enabled: bool = True
    target_crop_vision_enabled: bool = False
    overlay_revision_enabled: bool = True
    code_revision_enabled: bool = True
    min_display_score: int = 60
    min_non_background_ratio: float = 0.01
```

透明自检属于主 Agent 配置，不属于 Figure Agent 内部循环配置：

```python
pre_figure_reflexion_enabled: bool = False
```

该配置只控制是否在 Figure Agent 前运行透明自检；不提供后置反思模式。

返回：

```python
@dataclass
class FigureAgentResult:
    ok: bool
    best_asset_id: str | None
    best_image_url: str | None
    attempts: list[FigureAttempt]
    warnings: list[dict]
    final_score: int
    failure_reason: str | None
```

### 7.2 尝试记录

```python
@dataclass
class FigureAttempt:
    attempt_no: int
    source: str
    prompt_messages: list[dict]
    plan_type: str
    overlay_plan: dict | None
    code: str | None
    render_ok: bool
    security_blocked: bool
    image_url: str | None
    asset_id: str | None
    execution_error: str | None
    observation: dict
    score: int
    selected: bool = False
```

每次 attempt 都必须写入 Agent trace，便于复盘。

`source` 取值：

| 值 | 说明 |
|----|------|
| `existing_python_figure` | Solve 阶段已经输出的绘图代码，作为无法 overlay 或 overlay 失败后的候选 |
| `structured_renderer` | 结构化几何 renderer 生成的快速 attempt |
| `overlay_renderer` | 目标子图裁剪后的 overlay plan 渲染结果 |
| `draw_plan_llm` | Draw Plan LLM 生成的 overlay plan 或 fallback 绘图代码 |
| `revision_llm` | Revision LLM 根据 Observation 修正后的 overlay plan 或绘图代码 |

### 7.3 Trace 文件结构

Figure Agent trace 以「一次用户提交」为单位保存。建议目录：

```text
backend/.agent_traces/
└── {session_id}/
    └── {message_id}/
        ├── request.json
        ├── tool_process_question.json
        ├── tool_extract_knowledge.json
        ├── solve.md
        ├── auxiliary_text.json
        ├── figure_trigger.json
        ├── target_diagram_crop.json
        ├── point_location_crop.json
        ├── point_location.json
        ├── figure_goal.json
        ├── figure_context.json
        ├── attempts/
        │   ├── 01_existing_python_figure/
        │   │   ├── prompt.json
        │   │   ├── code.py
        │   │   ├── execution.json
        │   │   ├── observation.json
        │   │   └── image.png
        │   └── 02_revision_llm/
        │       ├── prompt.json
        │       ├── code.py
        │       ├── execution.json
        │       ├── observation.json
        │       └── image.png
        └── final.json
```

最小字段：

| 文件 | 必填内容 |
|------|----------|
| `request.json` | `session_id`、`message_id`、`asset_ids`、用户输入 |
| `solve.md` | 完整文字解答、原始 `python:figure` 代码块（若有） |
| `auxiliary_text.json` | 从 Solve 原文提取到的辅助线句和候选辅助线意图 |
| `figure_trigger.json` | `figure_needed`、`reason`、`auxiliary_intent`、`confidence`、`trigger_source` |
| `target_diagram_crop.json` | 目标子图标签、裁剪框、裁剪图 asset、坐标系和展示倍率 |
| `point_location_crop.json` | Point Locate 实际使用的裁剪框、来源、裁剪图尺寸和 warning |
| `point_location.json` | Vision LLM 点位定位结果、置信度和坐标映射 |
| `point_snap.json` | 本地像素吸附结果，包括原坐标、吸附坐标、偏移量、置信度和 warning |
| `figure_goal.json` | Goal Check 输出，包括 `expected_auxiliary`、`layout_hint` 和 warnings |
| `figure_context.json` | 传给 Figure Agent 的完整上下文 |
| `overlay_plan.json` | Draw Plan 输出的 overlay plan；若走 `python:figure` fallback，可为空 |
| `execution.json` | sandbox 状态、stderr 摘要、timeout、`security_blocked`、产物路径 |
| `observation.json` | 程序级检查、语义检查、keep / missing / wrong / style_issues / next_action、score |
| `final.json` | 选中的 attempt、最终 `asset_id`、warning、失败原因 |

trace 规则：

1. 成功和失败路径都必须保存 trace。
2. trace 中可保存内部错误和代码，但用户可见消息必须脱敏。
3. 图片文件可保存副本或保存 `asset_id` 引用；至少要能从 `final.json` 追到最终图片。
4. trace 写入失败不能影响主流程和 `figure_result` 输出，只记录日志 warning。

### 7.4 工具集合

Figure Agent 可使用的工具：

| 工具 | 职责 |
|------|------|
| `crop_target_diagram` | 从原始题图中截取当前小问对应的几何子图，并保存裁剪框和裁剪图资产 |
| `locate_points_on_crop` | 调用 Vision LLM 在裁剪图坐标系定位几何点 |
| `render_overlay` | 根据 overlay plan 在裁剪图或原图上叠加辅助线，输出用户可见图片 |
| `render_figure` | 执行 matplotlib 代码并生成图片 |
| `inspect_image_basic` | 程序检查图片尺寸、空白率、文件有效性 |
| `inspect_image_semantic` | 调用 Vision LLM 做语义检查 |

工具不负责：

- 生成辅助线策略。
- 改写证明过程。
- 判断数学证明严格性。

## 8. SSE 与前端展示

### 8.1 时序

```text
delta streaming
→ answer_end
→ reflexion_result（可选；透明输出给用户）
→ figure_attempt（可选，调试态）
→ figure_result
→ figure_warning（可选）
→ message_end
```

前端必须消费 `reflexion_result` 和 `figure_result`。绘图 attempt 等调试事件可先只写 trace，不一定展示在 UI 中。

前端归属规则：

1. `answer_end` 表示文字答案结束，前端收到后必须允许用户继续输入。
2. `reflexion_result` 是用户可见的透明自检结果，必须携带当前 `message_id`，并追加到同一个 AI 气泡。
3. `reflexion_result` 不能覆盖已经流式输出的文字答案；若存在修正版，应以「自检修正」形式追加展示。
4. `figure_result`、`figure_warning`、`figure_agent` 非致命失败事件必须携带当前 `message_id`，并挂回同一个 AI 气泡。
5. 后置绘图事件不能新建一条 AI 消息，不能覆盖已经流式输出的文字答案。
6. warning 只能作为图片旁的提示或调试信息，不能隐藏已生成的图片。
7. 绘图失败不能让输入框重新进入禁用状态。
8. 若用户在 Figure Agent 仍运行时继续追问，新一轮请求正常开始；旧消息的后置图片仍按 `message_id` 回填。

### 8.2 非致命失败

绘图失败不发送全局 `error`。推荐发送：

```json
{
  "event": "tool_result",
  "data": {
    "tool": "figure_agent",
    "data": {
      "status": "failed",
      "message": "辅助线图暂未生成，但文字解题已完成",
      "attempt_count": 2
    }
  }
}
```

### 8.3 Best Effort 展示

若图片可展示但存在低置信度问题：

```json
{
  "event": "tool_result",
  "data": {
    "tool": "figure_observation",
    "data": {
      "status": "warning",
      "score": 68,
      "message": "辅助线图为示意图，部分点位可能与原图不完全一致"
    }
  }
}
```

前端不应因为 warning 隐藏图片。

## 9. Prompt 设计

### 9.1 Solve Prompt

Solve Prompt 不再禁止绘图代码。建议改为：

1. 文字解题仍是第一目标。
2. 使用辅助线时，先用自然语言明确辅助线意图。
3. 可以输出 `【辅助线】...`，供 Figure Agent 提取目标；若没有该标记，Figure Agent 仍要从完整解答中提取辅助线原句。
4. 不要求 Solve 阶段一定输出 `python:figure`；绘图由 Figure Agent 接手。
5. 如果 Solve 阶段已经输出 `python:figure`，Figure Agent 应保留它作为 fallback 候选；有题图且裁剪、点位可用时，仍优先生成 overlay plan。
6. 辅助线描述必须尽量保留方向，例如「延长 AE 至点 F」和「延长 EA 至点 F」含义不同。

### 9.2 Goal Check Prompt

```text
你是几何绘图目标整理器。
请根据题目、题图描述、完整解答和辅助线意图，整理一份绘图目标。

要求：
- 不重新证明题目；
- 不评价辅助线是否最优；
- 只把需要画出来的原图元素、辅助线、新点、共线 / 垂直 / 等长标记整理清楚；
- 有题图时优先选择目标子图 overlay，而不是重画整张示意图；
- 保留有向延长线语义，AE 和 EA 不可混用；
- 如果辅助线意图缺失或矛盾，返回 conflict，但不要自己发明证明。

只输出 JSON：
{
  "goal_status": "ready",
  "render_mode": "overlay_on_crop",
  "normalized_auxiliary_intent": "",
  "expected_auxiliary": [],
  "original_figure_elements": [],
  "layout_hint": {},
  "style_requirements": {},
  "warnings": []
}
```

### 9.3 Point Locate Prompt

```text
你是几何图点位定位器。当前图片已经裁剪到目标几何图附近。

裁剪图尺寸：{width}x{height} 像素。
待定位点：A、B、C、D、E、H。
题目信息：{question_text}

请返回这些点在当前裁剪图中的像素坐标。坐标必须落在几何线段端点、交点、折点或顶点处，不要落在字母文字本身。

只输出 JSON：
{
  "points": {
    "A": {"x": 0, "y": 0, "confidence": 0.0}
  },
  "warnings": []
}
```

Point Locate Prompt 不注入完整解答、Goal Check、网格图、语义检查或 overlay plan。它只负责视觉点位定位，证明和绘图意图由后续 Goal Check / Draw Plan 处理。

### 9.4 Draw Plan Prompt

```text
你是几何辅助线绘图 Agent。
请根据题目、解答、目标图裁剪结果、点位定位和 Goal Check 输出生成 overlay 绘图计划。

目标：
- 在目标几何裁剪图上叠加辅助线；
- 清晰画出 Goal Check.expected_auxiliary 中的辅助线；
- 辅助线使用细虚线或半透明线；
- 标签可读；
- 只标新增点，尽量不覆盖原图已有字母；
- 延长线必须保留方向，ray: "AE" 表示从 A 经 E 往 E 外侧延长。

输出：
优先只输出 overlay plan JSON，不解释。
无法使用原图 overlay 时，才输出一个 python:figure 代码块。
```

### 9.5 Semantic Inspect Prompt

```text
你是几何图自检器。
请对照题目、Goal Check 输出、绘图代码和图片，判断图片是否表达了目标辅助线。

只输出 JSON：
{
  "has_diagram": true,
  "shows_original_figure": true,
  "shows_auxiliary_lines": true,
  "auxiliary_matches_text": true,
  "direction_matches_text": true,
  "keep": [],
  "missing": [],
  "wrong": [],
  "style_issues": [],
  "next_action": "revise_code",
  "confidence": 0.0,
  "suggested_fix": []
}
```

### 9.5 Revision Prompt

见第 5.2 节。Revision Prompt 必须强调只修代码，不重新解题。

## 10. 测试与验收

### 10.1 单元测试

| 测试 | 覆盖 |
|------|------|
| Figure code extraction | 从 LLM 输出中提取 `python:figure` |
| Sandbox failure observation | 语法错误、超时、无输出转成 Observation |
| Basic image inspection | 空白图、尺寸异常、非空图检测 |
| Best effort selection | 多次 attempt 选择最高分图片 |
| Goal check parsing | Goal Check 输出 `expected_auxiliary` / `layout_hint` / warnings |
| Revision prompt building | Observation.missing / wrong / stderr 被注入修正 Prompt |
| Revision guidance | Observation.keep 被保留，next_action 正确驱动 revise / redraw / accept |
| Trigger fallback | 绘图意图对象缺失或不完整时仍启动 Figure Agent |
| Code best-effort extraction | 非标准代码块或夹带说明时仍尝试提取绘图代码 |
| Low-score visible image | 低分但安全、非空、尺寸正常的图片仍展示 best effort |
| Target diagram crop | 从整页题图中截取当前小问对应几何图，并记录 crop 元数据 |
| Point location mapping | 裁剪图点位定位结果能映射到 overlay 坐标 |
| Directed ray rendering | `ray=AE` 和 `ray=EA` 方向相反，不能画反 |
| Overlay plan rendering | overlay plan 能在裁剪图上画出新增点、连线和标记 |

### 10.2 集成测试

使用 mock LLM 覆盖：

1. 首次生成代码成功，直接返回 `figure_result`。
2. 首次代码语法错误，Revision LLM 修正后成功。
3. 首次图片语义缺失，Vision LLM 给出 missing，Revision LLM 补图后成功。
4. 结构化渲染失败，但 LLM 绘图 fallback 成功。
5. 多次失败后，返回 best effort 或非致命 `figure_agent` 失败事件。
6. post-solve 绘图意图对象缺失，Figure Agent 根据题目和完整解答 fallback 成功。
7. Draw Plan 输出夹带说明或普通 Python 代码块，代码 best-effort 提取后成功渲染。
8. Revision 返回 `need_redraw_plan`，Figure Agent 重新生成绘图目标后继续渲染。
9. Observation 标记 `keep` 和 `missing` 后，Revision 保留正确部分并只补缺失辅助线。
10. Observation 返回 `next_action=accept_best_effort` 时，不再继续重画，直接展示当前最佳图。
11. 有题图时优先生成目标子图裁剪图和 overlay plan；无法定位点位时才 fallback 到 `python:figure`。
12. Solve 输出「延长 AE 至点 F，使 EF = AE」时，Draw Plan 输出 `ray="AE"`，渲染出的 F 位于 E 外侧。

### 10.3 Live 验收

至少使用 `tests/questions/几何-线段-全等.jpg` 验证：

1. Web 上传题图。
2. 主流程完整输出文字解答。
3. Figure Agent 至少产生 1 次绘图 attempt。
4. Trace 中能看到 Solve 使用生产解题模型、辅助线原文、目标图裁剪、点位定位、Draw Plan 和渲染结果。
5. 最终图优先展示裁剪后的几何图，而不是整页题干。
6. 若文字答案辅助线为「延长 AE 至点 F，使 EF = AE，连接 CF、BF」，最终图中的 F 必须位于 `AE` 延长方向，且显示 `CF`、`BF`。
7. 若图不准，Observation 能说明缺什么、哪里错或延长方向是否反了。
8. 最终前端可见 `figure_result` 或可读失败原因。

验收标准从「规则校验通过才画」调整为：

```text
只要安全可执行，系统应尽量生成图；
检查结果用于修正和提示，不用于默认阻断。
```

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 生成图与证明割裂 | 用户误解辅助线 | Vision LLM 自检；Revision LLM 根据 missing / wrong 修正；trace 留档 |
| 整页题图展示过小 | 辅助线和标签不可读 | 目标子图裁剪后再叠加，前端优先展示裁剪图 |
| 延长线方向画反 | 辅助线与文字答案不一致 | Draw Plan 使用 `ray` 有向语义；Vision Observation 检查 `direction_matches_text` |
| 点位定位偏差 | 辅助线端点偏移 | Vision LLM 只做粗定位；Point Snap 在局部窗口内把坐标吸附到几何线段端点、交点或折点；吸附失败时保留原坐标并把 warning 交给后续 Observation / Revision |
| LLM 绘图代码不稳定 | 无图或报错 | sandbox stderr 回传 Revision；最多重试 2 次；保留 best effort |
| 图像自检误判 | 错误图被放行或好图被重画 | 自检只作为 soft signal；不作为唯一阻断条件 |
| 成本增加 | 响应变慢 | Figure Agent 仅几何题触发；语义自检可按配置开启；默认最多 1 次 Revision |
| ReAct 循环失控 | 延迟和成本不可控 | 固定最大 attempt 数；每轮只允许 `render_figure` / `inspect_image` 工具 |
| 安全风险 | 任意代码执行风险 | sandbox 保持无网络、只读文件系统、超时和资源限制 |

## 12. 迁移计划

### 阶段 1：解除硬阻断

1. 移除结构化几何时禁止 `python:figure` 的 Prompt。
2. 结构化几何失败不再吞掉 legacy `python:figure`。
3. `geometry_validator` 失败改为 warning，不阻断 LLM 绘图 fallback。

### 阶段 2：Figure Agent 首版

1. 新增目标子图裁剪和点位定位工具。
2. 新增 Draw Plan LLM 调用，优先输出 overlay plan。
3. 新增 overlay renderer，在裁剪图上绘制辅助线并输出 2 倍展示图。
4. 保留 `SandboxService.render_figure` 作为无法 overlay 时的 fallback。
5. 记录 attempt trace。
6. 无图时使用 Figure Agent fallback。

### 阶段 3：Observation 与 Revision

1. 增加基础图片检查。
2. 增加 sandbox 错误到 Revision Prompt 的闭环。
3. 增加 Vision LLM 语义检查。
4. 根据 score 选择 best effort。

### 阶段 4：回归集与质量优化

1. 建立真实题图回归集。
2. 汇总失败 trace，优化 Figure Prompt。
3. 仅对高频稳定模式保留结构化增强，不再扩大规则穷举范围。

## 13. 第 16 题第（2）问样例

题目目标：

```text
已知 ∠BCA = 90°，CA = CB，∠CEA = 90°，AH + 2AE = BH。
求证 AH ⊥ BH。
```

Solve 输出可以包含：

```text
【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。
```

Figure Agent 的目标不是证明该辅助线一定最优，而是把这句话画清楚：

1. 原图包含 `A/B/C/D/E/H` 的基本位置。
2. 目标图优先截取「图 2」，并在裁剪图上叠加辅助线。
3. `F` 位于 `AE` 延长方向，即从 `A` 经 `E` 到 `E` 外侧；不能画到 `EA` 延长方向。
4. `EF = AE` 可用等长标记或 trace 说明表达；首版至少保证 `F` 的方向和位置合理。
5. `CF`、`BF` 为辅助线，使用细虚线或半透明线。
6. 若点位无法完全拟合原图，标注为示意图 warning，但仍展示。

Goal Check / Draw Plan 可以归一化为：

```json
{
  "normalized_auxiliary_intent": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。",
  "expected_auxiliary": [
    "F lies on the ray from A through E",
    "EF equals AE",
    "CF is connected",
    "BF is connected"
  ],
  "layout_hint": {
    "directed_rays": [
      {"ray": "AE", "meaning": "从 A 经 E 向 E 外侧延长"}
    ]
  }
}
```

Draw Plan 的 overlay plan 应包含：

```json
{
  "plan_type": "overlay_on_crop",
  "constructions": [
    {"op": "point_on_segment_by_distance", "point": "F", "ray": "AE", "from": "A", "distance": "2*AE", "role": "construction"},
    {"op": "connect_points", "points": ["C", "F"], "role": "construction"},
    {"op": "connect_points", "points": ["B", "F"], "role": "construction"}
  ]
}
```

如果首轮图把 `F` 画到 `EA` 方向，Observation 应返回：

```json
{
  "wrong": [
    "F is on the wrong extension direction"
  ],
  "suggested_fix": [
    "Use ray AE, meaning from A through E and beyond E.",
    "Keep CF and BF, but recompute F on the AE ray."
  ]
}
```

Revision LLM 据此修正 overlay plan 或绘图代码，而不是让代码继续补正则。
