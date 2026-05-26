# Sprint 4 History：结构化几何方案与调试记录

## 1. 文档定位

本文只记录 Sprint 4 在切换到 Figure Agent ReAct 之前的方案、实现进度和调试结论，作为历史追溯使用。

当前执行计划以 [planning.md](./planning.md) 为准；当前设计以 [design.md](./design.md) 为准。

## 2. 原结构化方案摘要

原 Sprint 4 的目标是建立一条可校验的结构化绘图闭环：

```text
题图识别
→ GeometrySceneCandidate
→ 文字解题
→ 抽取【辅助线】
→ 校验
→ 渲染 figure_result
```

原方案的核心原则：

1. 几何题识别拆为 `visual_observation` 和 `geometry_normalizer`。
2. `GeometrySceneCandidate` 区分 `observations`、`given_relations`、`auxiliaries`、`uncertain` 和 `warnings`。
3. `solve` 使用辅助线时必须输出独立的 `【辅助线】` 构造句。
4. `auxiliary_extractor` 从 `【辅助线】` 句抽取结构化 `AuxiliaryOperation`。
5. `geometry_validator` 校验辅助线引用、点序、构造来源和渲染可行性。
6. `geometry_renderer` 把通过校验的场景和辅助线渲染为 `figure_result`。

该方案在规则可覆盖的构造上有追溯性优势，但在真实辅助线场景中容易把抽取、校验和渲染变成硬闸门，导致文字解答已经提到辅助线却没有图。

## 3. 原计划交付项

原计划包含以下交付内容：

1. `GeometrySceneCandidate`：保存图形事实、题干关系和不确定项。
2. `solve` 辅助线输出规范：使用辅助线时必须输出 `【辅助线】` 构造句。
3. `auxiliary_extractor`：从 `【辅助线】` 句抽取结构化 `AuxiliaryOperation`。
4. `geometry_validator`：校验辅助线引用、点序、构造来源和渲染可行性。
5. `geometry_renderer`：把通过校验的辅助线渲染为 `figure_result`。
6. 至少 3 道真实几何题端到端回归。

## 4. 原任务进度

### Task 4.6.1：图形识别与 `GeometrySceneCandidate`

- [x] 将几何题识别拆为 `visual_observation` 和 `geometry_normalizer`。
- [x] VLM 只输出点、线、已画线段、标记、题干文字和不确定项。
- [x] `geometry_normalizer` 生成拓扑优先的 `GeometrySceneCandidate`。
- [x] 每条关系保留 `source`、`confidence` 和可选 `evidence`。
- [x] 文字关系优先于视觉猜测，冲突写入 `warnings`。
- [x] 非几何题输出 `geometry_scene_candidate=null`。

**原验收：** 第 16 题第（2）问能识别出 `A/B/C/D/E/H`、`D on BA`、`E/A/H` 共线、`C/D/H` 共线、`CA ⊥ CB`、`CA = CB`、`CE ⊥ EA` 和 `AH + 2AE = BH`。

**原验证：** `PYTHONPATH=. python3 -m pytest tests/test_geometry_normalizer.py tests/test_agent_tools.py -q`

### Task 4.6.2：解题输出辅助线契约

- [x] 修改 `solve` Prompt：使用辅助线时必须输出 `【辅助线】` 单独成句。
- [x] 明确 `solve` 只生成文字解题和辅助线构造句，不直接写自由 `python:figure`。
- [x] 支持无辅助线题目：不输出 `【辅助线】` 时，后续绘图模块不生成辅助线图。
- [x] 保留现有引导式解答和直接解答策略，不破坏学生优先规则。

**原验收：** 第 16 题第（2）问的文字解题中能出现类似 `【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。` 的可抽取构造句。

**原验证：** `PYTHONPATH=. python3 -m pytest tests/test_agent_layers.py -q`

### Task 4.6.3：辅助线抽取器

- [x] 新增 `auxiliary_extractor`，只读取 `【辅助线】` 句。
- [x] 优先规则解析常见句式：连接、延长、作垂线、取等长点、交点、中点、对称。
- [x] 规则解析失败时再调用文本模型兜底；不使用 `qwen-vl-max` 做纯文本抽取。
- [x] 抽取结果必须保留 `source_sentence`。
- [x] 抽取层禁止新增、替换、优化或猜测辅助线。

**原验收：** 输入 `【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF、BF。` 时，输出构造 `F`、连接 `CF`、连接 `BF` 3 个操作。

**原验证：** `PYTHONPATH=. python3 -m pytest tests/test_auxiliary_extractor.py -q`

### Task 4.6.4：几何校验与视觉复核

- [x] 校验操作引用的点、线、角是否存在。
- [x] 校验新点是否有唯一构造方式。
- [x] 校验操作必须可追溯到 `source_sentence`。
- [x] 校验操作只新增辅助元素，不修改原始题图关系。
- [x] 对低置信度点序、延长方向和图文冲突返回可解释错误。
- [x] 必要时调用 `qwen-vl-max` 做原图复核；复核结果只能进入 `uncertain` 或 `warnings`。

**原验收：** 校验失败时不生成错误图，而是返回 `geometry_check_failed` 和可读原因。

**原验证：** `PYTHONPATH=. python3 -m pytest tests/test_geometry_validator.py tests/test_agent_service_geometry.py -q`

### Task 4.6.5：受控渲染器与 `figure_result`

- [x] 将 `GeometryScene` 和通过校验的 `AuxiliaryOperation` 渲染为图片。
- [x] 对无坐标场景生成关系正确的示意布局。
- [x] 原题图元素和辅助线用不同样式展示。
- [x] 沿用现有 `figure_result` SSE 事件。
- [x] 保留沙箱策略：禁止网络、只读文件系统、超时和资源限制。

**原验收：** 辅助线图能显示原始点线和新增辅助线，并通过前端 `figure_result` 展示。

**原验证：** `PYTHONPATH=. python3 -m pytest tests/test_geometry_renderer.py tests/test_agent_service_geometry.py -q`；`npm run type-check`

### Task 4.6.6：几何辅助线回归集

- [ ] 从 `tests/questions/` 选择至少 3 道几何题。
- [ ] 每道题标注期望关键关系、`【辅助线】` 句、允许操作和禁止操作。
- [ ] 覆盖等腰直角、截长法、延长线交点、长度转移、全等证明等场景。
- [ ] 建立端到端验证：上传题图 → 识别 → 解题 → 抽取 → 校验 → 渲染。

**原验收：** 3 道题均能生成来源可追溯的辅助线图；错误或含糊构造不渲染。

## 5. 关键调试记录

### 5.1 图片题主流程修复

已确认并修复 Web 上传图片题在已有会话上下文下被 planning 误判为追问、跳过 `process_question` / `extract_knowledge` 的回归。服务端对本轮带图片资产的请求确定性补齐题目识别和知识点提取链路。

回归测试覆盖事件序列：

```text
分析题目中 → 识别题目中 → 提取知识点中 → 生成回复中
```

`tests/questions/几何-线段-全等.jpg` live 端到端链路曾跑到 `message_end`，事件包含 `process_question`、`extract_knowledge` 和 `delta`，无 `error`。但当时解题未输出 `【辅助线】`，未生成 `figure_result`；`current_geometry` 存在但点线数量为 0，不能满足完整闭环验收。

当时下一步判断为：修补 `visual_observation` 输出契约 / normalizer 映射和解题辅助线触发，再重跑真实题图回归。

### 5.2 输入禁用修复

已补充 `answer_end` SSE 事件，语义为文字答案已输出完毕。前端收到该事件后解除输入禁用，允许学生继续追问；后续 `figure_result`、`reflexion_patch` 和 `message_end` 仍归属于原 AI 气泡，不再阻塞下一轮输入。

回归测试覆盖：`answer_end` 必须位于最后一个 `delta` 之后、`figure_result` 和 `message_end` 之前。

### 5.3 辅助线图渲染修复

已确认普通辅助线句：

```text
【辅助线】延长 AE 至点 F，使 EF = AE，连接 CF。
```

能被抽取并通过校验。真实断点在无坐标 `GeometryScene` 渲染阶段。渲染器已补充无坐标示意布局，只有点名和已画线段时也能生成受控辅助线图并返回 `figure_result`。

### 5.4 结构化方案的局限

后续真实测试暴露的问题：

1. 结构化抽取和校验一旦失败，容易导致完全没有辅助线图。
2. Prompt 中限制 `python:figure` 会让 LLM 无法直接参与绘图补救。
3. 辅助线方式难以穷举，继续扩展正则和结构化操作会进入规则堆叠。
4. 检查本应服务于修正图，而不是让图消失。

这些问题直接推动当前方案切换为：主流程继续 Plan-and-Solve，辅助线绘图子流程采用 Figure Agent ReAct。

## 6. 第 16 题第（2）问历史样例

### 6.1 题干事实

- `∠BCA = 90°`，即 `CA ⊥ CB`。
- `CA = CB`。
- `D` 在线段 `BA` 上。
- `∠CEA = 90°`，即 `CE ⊥ EA`。
- 延长 `EA` 与 `CD` 交于 `H`，即 `E/A/H` 共线，`C/D/H` 共线。
- 已连接 `BH`。
- `AH + 2AE = BH`。
- 证明目标：`AH ⊥ BH`。

### 6.2 旧结构化抽取样例

当时文字解题输出的辅助线句：

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

历史结论：

- 从文字解题中抽取辅助线，比独立生成辅助线候选更稳定。
- `CF` 用于结合 `CE ⊥ EA` 与 `EF = AE` 得到 `CA = CF`。
- `BF` 在该证明中用于等腰三角形 `BFH`，不是绘图模块额外猜测出的线。
- 后续实现重点曾是让抽取、校验和渲染严格追溯到 `source_sentence`。

当前方案保留这种追溯能力作为增强路径，但不再把它作为能否绘图的前置条件。

## 7. 历史验证命令

历史阶段常用验证命令：

```bash
cd backend
PYTHONPATH=. python3 -m pytest \
  tests/test_agent_layers.py \
  tests/test_agent_tracing.py \
  tests/test_auxiliary_extractor.py \
  tests/test_agent_service_geometry.py \
  tests/test_geometry_renderer.py \
  tests/test_geometry_validator.py \
  -q
```

当时相关单元 / 集成测试曾达到 `46 passed`。后续执行应以当前 [planning.md](./planning.md) 中的新验收命令为准。
