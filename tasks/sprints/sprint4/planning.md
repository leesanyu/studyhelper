# Sprint 4 Planning：几何辅助线正确绘制

## 1. 目标

解决几何题辅助线绘制不稳定的问题。

Sprint 4 不追求自动证明器，也不让 LLM 独立猜辅助线。目标是建立一条可校验的绘图闭环：

```text
题图识别 → GeometrySceneCandidate → 文字解题 → 抽取【辅助线】 → 校验 → 渲染 figure_result
```

核心原则：**辅助线图必须来自正确文字解题中实际使用的构造句**。绘图模块只做抽取、校验和渲染，不重新发明证明策略。

## 2. 范围

**包含的 Story：**

- Story 4.6：几何辅助线正确绘制

**本 Sprint 要交付：**

1. `GeometrySceneCandidate`：保存图形事实、题干关系和不确定项。
2. `solve` 辅助线输出规范：使用辅助线时必须输出 `【辅助线】` 构造句。
3. `auxiliary_extractor`：从 `【辅助线】` 句抽取结构化 `AuxiliaryOperation`。
4. `geometry_validator`：校验辅助线引用、点序、构造来源和渲染可行性。
5. `geometry_renderer`：把通过校验的辅助线渲染为 `figure_result`。
6. 至少 3 道真实几何题端到端回归。

**不在本 Sprint 范围：**

1. 不实现完整自动几何证明器。
2. 不追求从任意复杂题图中 100% 还原所有关系。
3. 不让解题 LLM 直接输出自由 `matplotlib` 代码作为最终辅助线图。
4. 不让绘图模块独立生成辅助线候选。
5. 不改造前端主交互形态；前端继续消费后端 `figure_result` 事件。

## 3. 核心方案

### 3.1 模型职责

| 模型 / 模块 | 职责 | 不做什么 |
|-------------|------|----------|
| `qwen-vl-max` | 题图识别；必要时做原图视觉复核 | 不做完整解题，不生成辅助线策略 |
| `qwen3.6-plus` | 基于题干、图形关系和知识点生成文字解题 | 不直接写自由绘图代码 |
| `auxiliary_extractor` | 从 `solve` 的 `【辅助线】` 句抽取结构化操作 | 不新增、替换、优化辅助线 |
| `geometry_validator` | 校验场景和辅助线操作 | 不调用 LLM 解题 |
| `geometry_renderer` | 渲染通过校验的 `GeometryScene` | 不决定证明策略 |

### 3.2 数据流

```text
上传题图
→ visual_observation：识别点、线、标记、题干文字
→ geometry_normalizer：生成 GeometrySceneCandidate
→ solve：生成文字解题；若使用辅助线，输出【辅助线】句
→ auxiliary_extractor：抽取 AuxiliaryOperation
→ geometry_validator：校验引用、方向、来源和冲突
→ optional visual_review：只复核点序 / 延长方向 / 原图冲突
→ geometry_renderer：生成辅助线图
→ figure_result SSE
```

### 3.3 关键设计决策

1. **`GeometryScene` 是真相源，绘图代码是产物。**
   后续模块不维护自由 Python 代码，而是维护结构化点、线、关系和辅助操作。

2. **拓扑优先，坐标可选。**
   坐标只用于渲染布局，不作为识别阶段的事实来源。

3. **视觉事实、题干关系、辅助构造分层。**
   `observations` 只保存直接可见事实；`given_relations` 保存题干关系；`auxiliaries` 只保存解题后新增构造。

4. **题干文字优先于视觉猜测。**
   图像角度看起来不准时，仍以题干写明的垂直、相等、共线等条件为准。

5. **辅助线从文字解题抽取。**
   `solve` 必须显式输出构造句：

   ```text
   【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。
   ```

   `auxiliary_extractor` 只能抽取该句，不能重新生成候选。

6. **原图复核只做视觉校验。**
   VLM 复核可以判断点序、延长方向和图形冲突，不能新增辅助线，也不能覆盖题干关系。

## 4. 初版数据结构

### 4.1 `GeometrySceneCandidate`

```json
{
  "version": "1.0",
  "observations": {
    "points": [
      {"id": "A", "source": "vision", "confidence": 0.9}
    ],
    "drawn_segments": [
      {"id": "seg_CA", "endpoints": ["C", "A"], "source": "vision", "confidence": 0.9}
    ],
    "marks": []
  },
  "given_relations": [
    {"type": "perpendicular", "a": "CA", "b": "CB", "source": "text", "confidence": 1.0},
    {"type": "equal_length", "a": "CA", "b": "CB", "source": "text", "confidence": 1.0}
  ],
  "auxiliaries": [],
  "uncertain": [],
  "warnings": []
}
```

### 4.2 `AuxiliaryOperation`

初版支持以下受控操作：

- `connect`：连接两个已知点。
- `extend_line` / `extend_ray`：延长已有线段或射线。
- `construct_parallel`：过一点作已知直线的平行线。
- `construct_perpendicular`：过一点作已知直线的垂线。
- `reflect_point`：点关于直线对称。
- `midpoint`：构造中点。
- `intersection`：构造两条已知线的交点。
- `copy_segment_on_ray`：把已知线段长度转移到指定射线上。
- `construct_point_on_ray_with_distance`：在指定射线上按长度表达式截取点。

示例：

```json
{
  "type": "construct_point_on_ray_with_distance",
  "params": {
    "ray": "AE",
    "base_point": "E",
    "distance_ref": "AE",
    "new_point": "F"
  },
  "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。"
}
```

## 5. 任务拆分

当前任务拆分按端到端闭环重组，避免把每个内部模块都拆成独立 Story。每个 Task 都有明确输入、输出和验证点。

### Task 4.6.1：图形识别与 `GeometrySceneCandidate`

- [ ] 将几何题识别拆为 `visual_observation` 和 `geometry_normalizer`。
- [ ] VLM 只输出点、线、已画线段、标记、题干文字和不确定项。
- [ ] `geometry_normalizer` 生成拓扑优先的 `GeometrySceneCandidate`。
- [ ] 每条关系保留 `source`、`confidence` 和可选 `evidence`。
- [ ] 文字关系优先于视觉猜测，冲突写入 `warnings`。
- [ ] 非几何题输出 `geometry_scene_candidate=null`。

**验收：** 第 16 题第（2）问能识别出 `A/B/C/D/E/H`、`D on BA`、`E/A/H` 共线、`C/D/H` 共线、`CA ⊥ CB`、`CA = CB`、`CE ⊥ EA` 和 `AH + 2AE = BH`。

### Task 4.6.2：解题输出辅助线契约

- [ ] 修改 `solve` Prompt：使用辅助线时必须输出 `【辅助线】` 单独成句。
- [ ] 明确 `solve` 只生成文字解题和辅助线构造句，不直接写自由 `python:figure`。
- [ ] 支持无辅助线题目：不输出 `【辅助线】` 时，后续绘图模块不生成辅助线图。
- [ ] 保留现有引导式解答和直接解答策略，不破坏学生优先规则。

**验收：** 第 16 题第（2）问的文字解题中能出现类似 `【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。` 的可抽取构造句。

### Task 4.6.3：辅助线抽取器

- [ ] 新增 `auxiliary_extractor`，只读取 `【辅助线】` 句。
- [ ] 优先规则解析常见句式：连接、延长、作垂线、取等长点、交点、中点、对称。
- [ ] 规则解析失败时再调用文本模型兜底；不使用 `qwen-vl-max` 做纯文本抽取。
- [ ] 抽取结果必须保留 `source_sentence`。
- [ ] 抽取层禁止新增、替换、优化或猜测辅助线。

**验收：** 输入 `【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。` 时，输出构造 `F`、连接 `CF`、连接 `BF` 3 个操作。

### Task 4.6.4：几何校验与视觉复核

- [ ] 校验操作引用的点、线、角是否存在。
- [ ] 校验新点是否有唯一构造方式。
- [ ] 校验操作必须可追溯到 `source_sentence`。
- [ ] 校验操作只新增辅助元素，不修改原始题图关系。
- [ ] 对低置信度点序、延长方向和图文冲突返回可解释错误。
- [ ] 必要时调用 `qwen-vl-max` 做原图复核；复核结果只能进入 `uncertain` 或 `warnings`。

**验收：** 校验失败时不生成错误图，而是返回 `geometry_check_failed` 和可读原因。

### Task 4.6.5：受控渲染器与 `figure_result`

- [ ] 将 `GeometryScene` 和通过校验的 `AuxiliaryOperation` 渲染为图片。
- [ ] 对无坐标场景生成关系正确的示意布局。
- [ ] 原题图元素和辅助线用不同样式展示。
- [ ] 沿用现有 `figure_result` SSE 事件。
- [ ] 保留沙箱策略：禁止网络、只读文件系统、超时和资源限制。

**验收：** 辅助线图能显示原始点线和新增辅助线，并通过前端 `figure_result` 展示。

### Task 4.6.6：几何辅助线回归集

- [ ] 从 `tests/questions/` 选择至少 3 道几何题。
- [ ] 每道题标注期望关键关系、`【辅助线】` 句、允许操作和禁止操作。
- [ ] 覆盖等腰直角、截长法、延长线交点、长度转移、全等证明等场景。
- [ ] 建立端到端验证：上传题图 → 识别 → 解题 → 抽取 → 校验 → 渲染。

**验收：** 3 道题均能生成来源可追溯的辅助线图；错误或含糊构造不渲染。

## 6. 验收标准

1. 几何题识别分为视觉事实识别和题干规范化两步，不能由 VLM 直接生成最终 `GeometryScene`。
2. `GeometrySceneCandidate` 明确区分 `observations`、`given_relations`、`auxiliaries`、`uncertain` 和 `warnings`。
3. 坐标不是识别阶段的真相源，只作为渲染布局字段。
4. `solve` 使用辅助线时必须输出 `【辅助线】` 构造句。
5. `auxiliary_extractor` 只能从 `【辅助线】` 句抽取操作，不能独立生成辅助线策略。
6. 抽取出的每个 `AuxiliaryOperation` 必须保留 `source_sentence`。
7. 至少支持 `connect`、`extend_line`、`intersection`、`copy_segment_on_ray`、`construct_point_on_ray_with_distance` 5 类高频操作。
8. 校验失败时不生成错误图，而是返回可读失败原因。
9. 至少 3 道真实几何题通过端到端验证。
10. Sprint 3 聊天、图片上传、SSE、`figure_result` 流程不回归。

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| VLM 误识图形关系 | 后续解题上下文错误 | 视觉事实只作候选；题干文字优先；低置信度进入 `uncertain` |
| 文字解题正确但 `【辅助线】` 句缺失 | 无法抽取辅助线 | Prompt 强制辅助线单独成句；缺失时不画图并提示 |
| 抽取层重新猜辅助线 | 图和文字证明割裂 | 抽取器只读 `【辅助线】` 句，所有操作保留 `source_sentence` |
| 点序或延长方向不确定 | 辅助线位置错误 | validator 校验；必要时 VLM 只做视觉复核 |
| 纯文本抽取调用成本过高 | 延迟增加 | 规则解析优先，文本模型兜底；不使用视觉模型做纯文本抽取 |
| 渲染布局不像原图 | 用户理解困难 | 初版允许示意图，优先保证关系正确；后续再提升布局拟合 |
| Schema 过大 | Sprint 4 无法闭环 | 初版只覆盖初中几何高频关系和高频辅助操作 |

## 8. 开工前置条件

1. Sprint 3 的 H5 聊天、图片上传、SSE、`figure_result` 链路可用。
2. 沙箱镜像可执行绘图代码。
3. `tests/questions/` 中至少保留 3 张真实几何题图。
4. 明确 Sprint 4 初版只做「辅助线正确绘制」，不做完整自动证明。

## 9. 验证样例：第 16 题第（2）问

### 9.1 题干事实

- `∠BCA = 90°`，即 `CA ⊥ CB`。
- `CA = CB`。
- `D` 在线段 `BA` 上。
- `∠CEA = 90°`，即 `CE ⊥ EA`。
- 延长 `EA` 与 `CD` 交于 `H`，即 `E/A/H` 共线，`C/D/H` 共线。
- 已连接 `BH`。
- `AH + 2AE = BH`。
- 证明目标：`AH ⊥ BH`。

### 9.2 新方案验证记录

按当前方案测试该题时，模型链路为：

```text
qwen-vl-max 识别题干和图形关系
→ qwen3.6-plus 文字解题
→ qwen3.6-plus / 规则抽取辅助线操作
```

文字解题输出的辅助线句：

```text
【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。
```

抽取得到的操作：

```json
[
  {
    "type": "construct_point_on_ray_with_distance",
    "params": {
      "ray": "AE",
      "base_point": "E",
      "distance_ref": "AE",
      "new_point": "F"
    },
    "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。"
  },
  {
    "type": "connect",
    "params": {"points": ["C", "F"]},
    "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。"
  },
  {
    "type": "connect",
    "params": {"points": ["B", "F"]},
    "source_sentence": "延长 AE 至点 F，使 EF = AE，连接 CF、BF。"
  }
]
```

结论：

- 从文字解题中抽取辅助线，比独立生成辅助线候选更稳定。
- `CF` 用于结合 `CE ⊥ EA` 与 `EF = AE` 得到 `CA = CF`。
- `BF` 在该证明中用于等腰三角形 `BFH`，不是绘图模块额外猜测出的线。
- 后续实现重点是让抽取、校验和渲染严格追溯到 `source_sentence`。
