# Sprint 4 Planning：几何辅助线绘图 Agent

> 历史说明：本文件已切换为当前执行计划。切换前的结构化几何方案、已完成任务和调试记录保存在 [history.md](./history.md)，只用于追溯，不作为当前实施依据。

## 1. 目标

解决几何题辅助线绘制不稳定、容易被代码层限制中断的问题。

Sprint 4 的主目标调整为：

```text
主解题流程：Plan-and-Solve
辅助线绘图子流程：Figure Agent ReAct
```

主解题流程继续负责题目理解、工具调用、知识点提取和文字解答；辅助线绘图作为后置子流程，根据题目、解答、辅助线意图和题图观察生成图片，并通过「渲染 → 观察 → 修正」提高可用性。

核心原则：

1. **LLM 是大脑，代码是工具。** 代码负责工具、安全、trace 和编排，不用正则或几何规则穷举辅助线策略。
2. **先跑通，再变准。** 检查和校验用于修正与提示，不作为默认阻断。
3. **结构化几何是增强器，不是闸门。** `GeometrySceneCandidate`、`auxiliary_extractor`、`geometry_validator` 和 `geometry_renderer` 可以优先提供候选，但失败后必须回退到 LLM 绘图。
4. **`python:figure` 不再被禁止。** Solve 阶段可以产出绘图代码；Figure Agent 也可以生成和修正绘图代码。
5. **Best effort 可见。** 只要图片安全可执行且非空，应尽量向用户展示，并把不足写入 trace 和 warning。
6. **调度不全部硬化。** 代码只控制安全、资源、工具契约、trace 和最大尝试次数；辅助线策略、绘图路径和修正判断优先交给 LLM 通过 Observation 决策。
7. **限制必须服务于可见结果。** 新增检查必须产出 warning / Observation 和回退路径，不能把低置信度判断变成「不生成图」。

## 2. 范围

**包含的 Story：**

- Story 4.6：几何辅助线正确绘制

**本 Sprint 要交付：**

1. 解除现有 Prompt 和编排中的硬阻断，避免结构化抽取 / 校验失败导致完全不画图。
2. 新增 Figure Agent 编排：Trigger、Goal Check、Draw Plan、Render、Observation、Revision、Best Effort。
3. 复用 Python sandbox 执行 `python:figure`，并把执行错误、空白图、语义差距反馈给 Revision LLM。
4. 将结构化几何模块降级为可选增强路径，而不是唯一绘图路径。
5. 简化代码调度，让代码只提供工具和边界，避免继续把辅助线策略硬编码进服务层。
6. 每次提交试题保存关键步骤 trace：题目识别、知识点、Solve 输出、透明自检、触发判断、Goal Check、绘图代码、执行结果、Observation、Revision。
7. Web 端继续通过 SSE 展示 `answer_end`、`reflexion_result`、`figure_result`、warning 和 `message_end`，自检和绘图失败都不阻塞继续追问。
8. 对有题图的几何题优先使用「目标几何图裁剪 + 点位定位 + 原图 overlay」生成辅助线图，重画示意图只作为 fallback。
9. Draw Plan 必须保留有向延长线语义，`AE` 和 `EA` 不可当成无向线段处理。
10. 至少以 `tests/questions/几何-线段-全等.jpg` 第 16 题第（2）问完成 live 端到端验收。

完成定义：

- 后端和前端自动化测试是中间门禁，不是最终完成标准。
- Story 4.6 只有在 Task 4.6.9 的真实 Web 上传题图端到端验收通过后，才能标记完成。
- 若自动化测试通过但端到端验收失败，继续按 trace 和日志修复，不能关闭 Sprint 4。

**不在本 Sprint 范围：**

1. 不实现完整自动几何证明器。
2. 不追求从任意复杂题图中 100% 还原所有关系。
3. 不要求辅助线图比例与原题图完全一致；有题图时优先展示裁剪后的原图 overlay，无法定位时允许清晰示意图。
4. 不把主 Agent 改造成全局 ReAct；ReAct 只用于辅助线绘图子流程。
5. 不继续扩大规则穷举范围来覆盖所有辅助线类型。

## 3. 核心方案

详细设计见 [design.md](./design.md)。本节只保留执行层需要追踪的方案摘要。

### 3.1 数据流

```text
上传题图
→ Plan：判断是否需要 process_question / extract_knowledge
→ Tool：识别题目、提取知识点、生成可选视觉观察
→ Solve：输出文字解题和辅助线意图
→ answer_end：文字答案结束，前端允许继续输入
→ Transparent Reflexion：透明自检，输出 `reflexion_result` 给用户
→ Figure Agent ReAct（可选）
   → Goal Check：LLM 整理 expected_auxiliary、layout_hint 和样式目标
   → Target Crop：截取当前小问对应的目标几何图
   → Point Locate：Vision LLM 在裁剪图上定位点位
   → Auxiliary Text：保存 Solve 原文中的辅助线句
   → Draw Plan：LLM 生成 overlay plan；无法 overlay 时 fallback 到 `python:figure`
   → Render Tool：优先在裁剪图上 overlay；必要时 sandbox 执行 matplotlib 代码
   → Observation：程序检查 + 可选 Vision LLM 语义检查
   → Revision：失败或缺失时修正代码，最多 1 到 2 次
   → Best Effort：选择最可用图片
→ figure_result / figure_warning
→ message_end
```

### 3.2 现有代码改造范围

| 文件 / 模块 | 当前问题 | 改造任务 |
|-------------|----------|----------|
| `backend/app/agent/prompts.py` | Solve / geometry Prompt 中仍存在禁止或弱化 `python:figure` 的倾向；Draw Plan Prompt 还偏向重画示意图，缺少 overlay plan 和有向射线契约 | 移除硬禁令；补充 Goal Check、overlay-first Draw Plan、Revision、Semantic Inspect Prompt；明确 `ray="AE"` 和 `ray="EA"` 的方向差异；要求保存辅助线原文 |
| `backend/app/agent/layers.py` | 主要覆盖 plan / solve / reflexion，缺少绘图子流程 LLM 调用边界 | 增加 Figure Agent 所需的 goal check、draw、revision、semantic inspect 调用封装或等价方法；补充透明自检结果结构 |
| `backend/app/agent/service.py` | 结构化几何路径容易成为主路径；失败时可能吞掉 legacy `python:figure` 或不触发绘图；当前反思仍有后置兼容分支 | 新增 post-solve 触发判断和 `run_figure_agent` 编排；保证结构化失败转 Observation；保证无结构化结果时走 LLM 绘图 fallback；移除后置反思，改为 `answer_end` 后透明输出 `reflexion_result` |
| `backend/app/agent/auxiliary_extractor.py` | 规则抽取容易被当成唯一入口 | 改为辅助线目标提取器；失败只产出 warning，不阻断 Figure Agent |
| `backend/app/agent/geometry_validator.py` | 校验失败会导致不渲染 | 改为 warning / Observation 来源，不决定是否最终展示 |
| `backend/app/agent/geometry_renderer.py` | 受控渲染效果不稳定时缺少 LLM 修正闭环 | 作为首轮快速 attempt；失败后把错误交给 Revision LLM |
| `backend/app/agent/figure_overlay.py`（新增或等价模块） | 当前 Figure Agent 主要重画示意图，不能稳定保留原题图结构 | 实现目标子图裁剪、点位坐标映射和裁剪图 overlay 渲染；输出放大后的用户可见图片 |
| `backend/app/agent/tracing.py` | 已有 trace 能力需要覆盖绘图 attempt | 记录每次题目提交的识别、Solve、透明自检、触发判断、Goal Check、绘图代码、sandbox 输出、Observation 和最终图片 |
| `backend/app/core/config.py` | 缺少 Figure Agent 行为开关；反思位置开关语义不准确 | 增加最大 attempt、是否启用语义检查、最低展示分等配置；将反思位置开关迁移为 `pre_figure_reflexion_enabled` |
| `backend/tests/*geometry*`、`backend/tests/test_agent_service_geometry.py` | 测试仍偏向结构化闭环 | 改为覆盖 fallback、Revision、best effort 和非致命失败 |
| `frontend/src/pages/chat/index.vue`、`frontend/src/utils/sse.ts` | 前端需要兼容 `answer_end` 后的自检、图片和 warning | 确认 `answer_end` 后输入可用；`reflexion_result`、`figure_result` / warning / 非致命失败携带 `message_id` 并挂到原 AI 气泡；自检修正不覆盖原答案，warning 不隐藏图片 |

### 3.3 结构化几何模块的新定位

现有结构化模块不删除，但职责调整：

1. `geometry_normalizer`：给 Figure LLM 提供结构化参考，不作为唯一真相源。
2. `auxiliary_extractor`：从 `【辅助线】` 或自然语言解答中提取候选目标；失败不阻断绘图。
3. `geometry_validator`：输出可解释 warning 和 Observation；不再作为展示闸门。
4. `geometry_renderer`：可作为快速受控渲染 attempt；失败后转入 LLM 绘图与 Revision。
5. `figure_overlay`：作为有题图几何题的优先渲染路径，负责目标图裁剪、点位坐标映射、有向辅助线叠加和裁剪图输出。

## 4. 任务拆分

当前任务拆分按「先解除硬阻断，再接入 Figure Agent，再做观察和回归」推进。每个 Task 完成后同步更新本文件状态。

### Task 4.6.0：设计与计划同步

- [x] 将 [design.md](./design.md) 调整为「主流程 Plan-and-Solve，辅助线绘图子流程 ReAct」。
- [x] 明确结构化几何模块是增强器，不是闸门。
- [x] 明确 `python:figure` 不再被禁止。
- [x] 补充实施任务和现有代码改造范围。

**验收：** `design.md` 和本 planning 不再把结构化校验通过作为唯一绘图条件。

**验证：** `git diff --check -- tasks/sprints/sprint4/design.md tasks/sprints/sprint4/planning.md`

### Task 4.6.1：解除现有硬阻断

- [x] 修改 `backend/app/agent/prompts.py`，移除禁止 `python:figure` 的 Prompt 约束。
- [x] 新增或调整 post-solve 触发判断：优先由 LLM 输出轻量绘图意图对象，包含 `figure_needed`、`reason`、`auxiliary_intent`、`confidence`、`existing_python_figure`。
- [x] 触发对象缺失、字段不完整或置信度偏低时，只记录 warning；本轮有题图且解答包含几何点线角描述时，仍启动 Figure Agent fallback。
- [x] 修改 `backend/app/agent/service.py`，结构化抽取 / 校验 / 渲染失败时不标记绘图完成，必须继续尝试 legacy `python:figure` 或 Figure Agent fallback。
- [x] 保留 Solve 阶段输出的 `python:figure`，作为无法走原图 overlay 或 overlay 失败后的 sandbox 候选。
- [x] 让 `geometry_validator` 失败返回 warning / Observation，不再直接成为「不画图」理由。
- [x] 增加回归测试：结构化校验失败但 LLM 绘图代码成功时仍发送 `figure_result`。
- [x] 增加触发回归测试：绘图意图对象缺失或 `auxiliary_intent` 为空时，Figure Agent 仍根据完整题目和解答启动，并写入 warning。

**验收：** 有辅助线意图但结构化链路失败时，后端仍至少产生 1 次绘图 attempt；绘图触发不能退回纯关键词硬判。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_service_geometry.py tests/test_agent_layers.py -q`

### Task 4.6.2：Figure Agent 首版编排

- [x] 在 `backend/app/agent/service.py` 新增 `run_figure_agent(...)` 内部编排方法。
- [x] 定义 `FigureAgentResult`、`FigureAttempt`，记录 `code`、`render_ok`、`image_url`、`execution_error`、`observation`、`score`。
- [x] 在 `backend/app/agent/layers.py` 或等价位置新增 Goal Check 和 Draw Plan LLM 调用。
- [x] Goal Check 输入包含题干、题图描述、完整解答、辅助线意图和结构化候选，输出 `expected_auxiliary`、`original_figure_elements`、`layout_hint`、`style_requirements` 和 warnings。
- [x] Draw Plan 输入使用 Goal Check 输出作为稳定绘图目标，不由代码自行改写辅助线策略。
- [x] Draw Plan 首版已支持 `python:figure` 代码块和 best-effort 代码提取；正式目标改为 Task 4.6.8 的 overlay-first，有题图且裁剪、点位可用时优先输出 overlay plan。
- [x] 无法提取可执行代码时，记录「未提取到绘图代码」Observation，并进入 Revision 或重新 Draw Plan，而不是直接终止 Figure Agent。
- [x] 在首版编排中接入最小 trace：保存 `figure_trigger.json`、`figure_goal.json`、Draw Plan 输出、提取后的代码、execution 和基础 Observation；完整目录整理可留到 Task 4.6.5。
- [x] 复用现有 sandbox 渲染图片并发送 `figure_result`。

**验收：** 没有结构化 `AuxiliaryOperation` 时，Figure Agent 也能先形成 Goal Check，再根据题目和解答生成图；非标准代码块可被 best-effort 提取并尝试渲染；失败时已有最小 trace 可定位到 Draw Plan / Render 阶段。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_service_geometry.py tests/test_agent_tracing.py -q`

### Task 4.6.3：Observation 与 Revision 闭环

- [x] 新增基础图片检查：PNG 是否存在、尺寸是否正常、是否非空白。
- [x] sandbox 语法错误、超时、无输出、空白图都转成结构化 Observation。
- [x] 程序级 Observation 至少包含 `execution`、`image_quality`、`security_blocked`、`score` 和 `next_action`；语义字段可为空，但结构必须预留。
- [x] 新增 Revision LLM 调用，将 Goal Check、上一版代码、stderr、程序级 Observation 和基础 `suggested_fix` 传回 LLM。
- [x] 支持 `next_action=revise_code`：优先修代码错误、无输出、空白图和明显样式问题。
- [x] 支持 `next_action=redraw_plan` 或 Revision 返回 `need_redraw_plan`：回到 Goal Check / Draw Plan 重新整理目标，不由代码改写证明。
- [x] 支持 `next_action=accept_best_effort`：停止继续重画，选择当前最佳安全非空图片并输出 `figure_result`。
- [x] 已接入旧版 `reflexion_before_figure_enabled` 位置开关；该方案后续按 Task 4.6.3a 迁移为透明自检，并移除后置反思路径。
- [x] 默认最多 2 次 attempt；仅明确代码错误时允许第 3 次 attempt。
- [x] 引入 best effort 选择：执行成功、非空白、辅助线匹配度较高的图片优先。
- [x] 绘图失败时发送非致命 `tool_result(tool="figure_agent")`，不发送全局 `error`。

**验收：** 首次 `python:figure` 报错、超时、无输出或空白图时，Revision LLM 能修正后生成 `figure_result`；多次失败时文字答案不回滚，并返回非致命失败或 best effort。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_service_geometry.py tests/test_agent_tracing.py -q`

### Task 4.6.3a：透明自检与后置反思移除

- [x] 将反思层定位为「文字答案之后、Figure Agent 之前」的透明自检，不再保留后置反思路径。
- [x] 将 `reflexion_before_figure_enabled` 位置开关迁移为 `pre_figure_reflexion_enabled`，语义只表示是否启用透明自检。
- [x] `answer_end` 后继续允许用户输入，随后发送 `reflexion_result` SSE 事件；事件必须携带 `message_id` 并追加到同一个 AI 气泡。
- [x] `reflexion_result` 至少包含 `status`、`visible_message`、`corrected_content`、`issues` 和 `figure_guidance`。
- [x] 自检发现原答案有问题时，向用户展示修正说明或修正版；不能只在后台静默修改 Figure Agent 上下文。
- [x] 自检超时、报错或结论不可靠时，向用户输出可读原因；该状态作为 Figure Agent 的 Observation，不作为默认硬阻断。
- [x] Figure Agent 输入增加 `reflexion_result`；若存在修正版，优先用修正版整理绘图目标，否则使用原答案和风险提示继续 best effort。
- [x] 移除后置 `reflexion_patch` 分支，避免文字和后置图片出现不一致的异步修正。
- [x] Trace 记录自检输入、输出、状态、usage、错误和传给 Figure Agent 的最终上下文。
- [x] 增加后端回归测试：通过、修正、不可靠、超时 / 报错 4 类自检结果都能产生用户可见事件，且不阻塞 `answer_end`。
- [x] 增加前端回归或类型验证：`reflexion_result` 能挂回原 AI 气泡，修正版不覆盖原流式答案。

**验收：** 用户先看到文字答案，再看到透明自检结果；后置反思路径不存在；Figure Agent 使用透明自检结果作为上下文，且自检异常不会让本轮悄悄失败或锁住输入。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_service_geometry.py tests/test_chat_api.py -q`；`cd frontend && npm run type-check`

### Task 4.6.4：可选 Vision 语义检查

- [x] 在配置中增加 `figure_semantic_inspection_enabled` 开关，默认可关闭。
- [x] 增加 Vision LLM 自检 Prompt：判断是否有原图骨架、辅助线、缺失项和错误项。
- [x] 将 Vision 输出转成 Observation，字段包含 `keep`、`missing`、`wrong`、`style_issues`、`next_action` 和 `suggested_fix`，供 Revision LLM 修正。
- [x] 语义 Observation 使用 Goal Check 的 `expected_auxiliary` 作为参照，不让代码自行推导辅助线策略。
- [x] 自检结果只作为 soft signal，不作为唯一阻断条件。
- [x] 为语义缺失场景增加 mock 测试：首轮缺 `CF` / `G`，Revision 后补齐。

**验收：** 语义检查发现缺少辅助线时，Observation 能指出 `keep` / `missing` / `wrong` 并根据 `next_action` 进入 Revision、重新 Draw Plan 或接受 best effort；即使自检低分，仍能展示 best effort 或可读失败原因。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_service_geometry.py -q`

### Task 4.6.5：Trace 文件与复盘能力

- [x] 扩展 `backend/app/agent/tracing.py`，每次提交试题保存分步骤输出。
- [x] Trace 至少包含：request / session、asset_ids、题目识别结果、知识点、Solve 输出、透明自检、辅助线意图、每轮绘图代码、sandbox stderr、Observation、最终图片 asset。
- [x] Trace 保存 `figure_goal.json`，包含 Goal Check 的 `expected_auxiliary`、`layout_hint`、`style_requirements` 和 warnings。
- [x] 在 Task 4.6.2 最小 trace 的基础上，整理成按 `session_id/message_id/attempt` 分层的复盘目录或等价结构。
- [x] Trace 文件按 `session_id`、`message_id` 或时间戳组织，避免不同请求互相覆盖。
- [x] 在失败路径也保存 trace，便于复盘为什么没有生成图。
- [x] 测试覆盖 trace 中存在 Figure Agent attempt 记录。

**验收：** 手动 Web 测试后，可以在 trace 目录看到每一步输出文件，并能定位绘图失败发生在哪一轮。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_tracing.py tests/test_agent_service_geometry.py -q`

### Task 4.6.6：前端 SSE 兼容与交互确认

- [x] `answer_end` 后解除输入禁用，允许学生继续追问。
- [x] 后端 `figure_result`、`figure_warning` / `figure_observation`、`figure_agent` 非致命失败事件必须携带当前 `message_id`。
- [x] 前端 SSE 类型和处理逻辑支持 `message_id`，优先按 `message_id` 挂回原 AI 气泡；缺失时才使用当前流式消息 fallback。
- [x] 确认后置 `figure_result` 会追加到原 AI 气泡，而不是新开错误消息。
- [x] 增加 `figure_warning` / `figure_agent` 非致命失败展示或降级处理。
- [x] 确认 warning 不隐藏图片，失败不影响下一轮输入。
- [x] 保持已有上传图片、SSE、Markdown / KaTeX 渲染不回归。

**验收：** 文字答案结束后输入可用；用户继续追问后，旧消息的辅助线图晚到仍能按 `message_id` 回填；绘图失败只显示提示，不锁住聊天。

**验证：** `cd frontend && npm run type-check`；必要时 `npm run build:h5`

### Task 4.6.7：自动化回归测试

- [x] 覆盖纯文字题：仍有「分析题目中 → 识别题目中 → 提取知识点中 → 生成回复中」进度。
- [x] 覆盖图片题：本轮带 `asset_ids` 时必须执行 `process_question` 和 `extract_knowledge`。
- [x] 覆盖 Figure Agent 触发：绘图意图对象缺失、字段不完整、`auxiliary_intent` 为空时仍按 fallback 启动并记录 warning。
- [x] 覆盖 Solve 输出 `python:figure`：直接进入 sandbox。
- [x] 覆盖 Goal Check：Draw Plan 前生成 `expected_auxiliary`、`layout_hint` 并写入 trace。
- [x] 覆盖 Draw Plan fallback：无结构化辅助线也能生成图。
- [x] 覆盖 Draw Plan 非标准输出：普通 Python 代码块或夹带说明时 best-effort 提取并尝试渲染。
- [x] 覆盖 sandbox 报错 → Revision → 成功。
- [x] 覆盖 Observation Guidance：`keep` / `missing` / `wrong` / `style_issues` / `next_action` 能驱动 Revision、redraw 或 accept。
- [x] 覆盖结构化渲染失败 → LLM fallback 成功。
- [x] 覆盖结构化渲染成功不短路 Figure Agent：结构化结果作为 `structured_renderer` attempt 进入 Observation；语义检查要求修正时进入 Revision。
- [x] 覆盖后置 `figure_result` 携带 `message_id`，前端能挂回原 AI 气泡。
- [x] 覆盖多次失败 → 非致命失败事件 + trace。
- [x] 覆盖 `reflexion_result` 携带 `message_id`，前端能挂回原 AI 气泡。
- [x] 覆盖自检修正、不可靠、超时 / 报错时的用户可见输出和 Figure Agent 上下文传递。
- [x] 覆盖后置反思路径已移除，不再发送旧的后置 `reflexion_patch`。

**验收：** 与 Agent、几何、SSE、trace 相关的后端测试全部通过。

**验证：**

```bash
cd backend
PYTHONPATH=. python3 -m pytest \
  tests/test_agent_layers.py \
  tests/test_agent_tracing.py \
  tests/test_auxiliary_extractor.py \
  tests/test_agent_service_geometry.py \
  tests/test_geometry_renderer.py \
  tests/test_geometry_validator.py \
  tests/test_chat_api.py \
  -q
```

### Task 4.6.8：目标图裁剪 Overlay 产品化

- [x] 新增目标几何图裁剪工具：从整页题图中定位当前小问子图，保存 `target_diagram`、`crop_box`、裁剪图资产和坐标系。
- [x] 清理正式 overlay 流程里的试验路径：不再先用 VLM 裁剪图做点位定位；整页点位定位不作为默认 fallback。
- [x] 点位定位优先使用本地版面裁剪得到的稳定 `point_location_crop`；VLM 目标裁剪只在本地裁剪不可用时兜底。
- [x] `infer_layout_crop_box` 对 `tests/questions/几何-线段-全等.jpg` 第 16 题第（2）问输出接近 demo 验证裁剪框 `[1260, 823, 2090, 1655]`。
- [x] 新增点位定位工具：调用 Vision LLM 在裁剪图坐标系定位 `A/B/C/D/E/H` 等点，保存置信度和映射结果。
- [x] 新增点位本地吸附工具：在 Vision LLM 粗坐标附近寻找线段端点、交点或折点，输出 `raw_points`、吸附后点位、偏移量、置信度和 warning；吸附失败时保留 VLM 原坐标，不阻断绘图。
- [x] 点位定位 Prompt 最小化：只包含裁剪图尺寸、待定位点和必要题目信息，不注入完整解答、Goal Check、网格图或语义检查要求。
- [x] Figure Agent 输入增加 `target_diagram`、`localized_points`、`auxiliary_text`，并写入 trace。
- [x] Solve / Trigger / Goal Check 必须打印并保存文字答案中的辅助线原句；不能只依赖 `auxiliary_extractor` 正则结果。
- [x] 模型路由必须和生产一致：`solving`、`figure_draw`、`figure_revision` 使用 `qwen3.6-plus`；`vision`、`figure_semantic_inspection` 使用 `qwen-vl-max-latest`，并写入 trace。
- [x] Goal Check 输出增加 `render_mode=overlay_on_crop`、`coordinate_space=crop_pixels`、`directed_rays` 和 `expected_auxiliary`。
- [x] Draw Plan 优先输出 overlay plan；无法裁剪或定位时才 fallback 到 `python:figure`。
- [x] Overlay plan 支持 `point_on_segment_by_distance`、`connect_points`、`highlight_segment`、`right_angle_marker`、`note` 等操作。
- [x] Overlay plan 必须使用有向 `ray` 表达延长线：`AE` 表示从 `A` 经 `E` 向外延长，`EA` 表示从 `E` 经 `A` 向外延长。
- [x] Overlay renderer 在裁剪图上绘制辅助线，优先输出 2 倍或等效高清裁剪图；线条使用细虚线或半透明线，不遮挡原图标签。
- [x] 增加 overlay 程序级语义检查：基于 `localized_points`、`computed_points`、`overlay_plan`、`auxiliary_text` 和 `expected_auxiliary` 检查漏画连线、等长约束和延长线外侧关系；检查结果只产出 Observation 触发 Revision，不阻断 best-effort 展示。
- [ ] Vision Observation 增加方向检查：若 `AE` / `EA` 画反，输出 `wrong` 和可执行 `suggested_fix`。
- [x] Trace 增加 `target_diagram_crop.json`、`point_location.json`、`point_snap.json`、`auxiliary_text.json`、`overlay_plan.json`、`overlay_render_trace.json` 和最终裁剪图。
- [x] 单元测试覆盖 `ray=AE` 和 `ray=EA` 方向相反、`EF=AE` / `AF=2AE` 的点位计算、裁剪图 overlay 产物非空。
- [x] 单元测试覆盖 VLM 坐标落在字母附近时吸附到几何顶点，以及无可靠候选时保留原坐标的 best-effort 行为。
- [x] 单元与集成测试覆盖程序级语义检查：漏画 `BF`、错误满足 `AF=AE` 而非 `EF=AE`、局部成功但存在 unsupported op 时均触发 Revision。

**验收：** 使用生产解题模型输出的辅助线「延长 AE 至点 F，使 EF=AE，连接 CF、BF」时，Draw Plan 生成 `ray="AE"`，最终裁剪图中的 `F` 位于 `E` 外侧，并显示 `CF`、`BF`，trace 中可复盘辅助线原文、VLM 原始点位、吸附后点位和 overlay plan。

**验证：** `cd backend && PYTHONPATH=. python3 -m pytest tests/test_figure_overlay.py tests/test_agent_layers.py tests/test_agent_service_geometry.py tests/test_agent_tracing.py tests/test_geometry_renderer.py tests/test_llm_client.py -q`；用 `tests/questions/几何-线段-全等.jpg` 或真实 trace 裁剪图复核 `point_snap` 原坐标、吸附坐标和最终 overlay。

**最新验证（2026-05-25）：**

- `cd backend && PYTHONPATH=. python3 -m pytest tests/test_config.py tests/test_agent_layers.py tests/test_agent_service_geometry.py tests/test_figure_overlay.py -q`：53 passed。
- `cd backend && PYTHONPATH=. python3 -m pytest tests/test_agent_layers.py tests/test_agent_tracing.py tests/test_auxiliary_extractor.py tests/test_agent_service_geometry.py tests/test_geometry_renderer.py tests/test_geometry_validator.py tests/test_chat_api.py tests/test_figure_overlay.py tests/test_llm_client.py tests/test_config.py -q`：90 passed。
- `git diff --check`：无输出。
- 真实 trace 裁剪图点位吸附 sanity：`/tmp/studyhelper-point-snap-sanity-20260525140845`，`A/B/C/D/E/H` 均从 VLM 粗坐标吸附到附近几何线段候选，`warnings=[]`。
- 修正 E 点误吸附到字母笔画的问题：Point Snap 会过滤紧凑小连通域中的文字标签候选，优先选择同一搜索窗口内的主几何线段连通域。新增回归 `test_snap_localized_points_prefers_geometry_component_over_isolated_label`，扩展回归 `91 passed`。新 debug 目录：`/tmp/studyhelper-point-snap-sanity-20260525142354`，其中 `E: raw=(370,120) -> snap=(344,148)`。
- 修正 C 点密集多线汇聚时偏向墨迹团块内部的问题：Point Snap 在存在多分支汇聚时使用局部骨架化候选，优先吸附到中心线骨架 junction。新增回归 `test_snap_localized_points_uses_skeleton_junction_for_dense_convergence`，扩展回归 `92 passed`。新 debug 目录：`/tmp/studyhelper-point-snap-sanity-20260525143421`，其中 `C: raw=(190,60) -> snap=(190,87)`，`E: raw=(370,120) -> snap=(345,147)`。
- 增加 overlay 程序级语义检查与修正链路：新增 `inspect_overlay_semantics`，发现漏画 `BF`、`EF=AE` 不满足或 renderer 局部成功 warning 时输出 `overlay_programmatic_observation`，交给 `figure_overlay_revision_plan` 修正；Revision 后再次检查并记录 trace，仍失败时展示 best effort。新增回归 `test_inspect_overlay_semantics_requests_revision_for_missing_connection`、`test_inspect_overlay_semantics_detects_wrong_equal_length_constraint`、`test_agent_service_revises_overlay_when_programmatic_check_finds_missing_connection`，扩展回归 `95 passed`。
- 优化 Figure Agent 执行链：有辅助线文本时跳过 `figure_trigger` LLM；`figure_goal`、VLM 目标裁剪、overlay revision、python code revision 均增加配置开关。关闭检查/修正时走本地轻量回退或展示 best effort，不阻断文字答案和已有图。新增回归 `test_agent_service_skips_trigger_llm_when_auxiliary_text_exists`、`test_agent_service_uses_local_goal_when_goal_llm_disabled`、`test_agent_service_skips_overlay_revision_when_disabled`、`test_agent_service_skips_code_revision_when_disabled`、`test_agent_service_uses_layout_crop_without_vlm_target_crop_for_point_location`；扩展回归 `99 passed`。
- 优化 Web 后置辅助线等待体验：`answer_end` 后保持输入可用，但当前 AI 气泡展示“答案已生成，正在处理辅助线图…”；`message_end` 前暂不展示“不甚理解 / 我会了”反馈按钮，避免用户在 Figure Agent 后置流程未归档时触发反馈。新增前端状态回归 `frontend/tests/chat_ui_state.test.mjs`；验证 `node tests/chat_ui_state.test.mjs`、`npm run type-check`、`npm run build:h5` 通过。
- 修正正式 Web 流程点位质量低于 demo 的根因：H5 上传和后端保存默认长边从 1600 提升到 3000，JPEG / WebP 质量提升到 92，`uni.chooseImage` 改为取原图后由前端受控压缩，避免图 2 裁剪从 demo 的约 `830x832` 降到正式流程的约 `432x441`。新增 `frontend/tests/image_quality.test.mjs`、配置回归和低分辨率 C 点 snap 回归；辅助线新构造点标签增大、优先粗体并加描边。验证 `108 passed`、`npm run type-check`、`npm run build:h5`、`git diff --check` 通过。
- 修正 `20260525T105901.060977Z_b63183bf-96de-4ab8-8b17-dea7acc2861c_284821f1` 手动 Web 测试暴露的问题：辅助线文本为「过点 C 作 CK⊥CE 且 CK=CE，连接 BK、KH」，原 overlay plan 错把 K 放到 `CE` 射线上，且 Figure Agent 后置绘图阶段触发 `figure_goal`、`point_location`、`figure_draw`、`figure_revision` 4 次模型请求。新增 `point_on_perpendicular_by_distance` overlay op、垂直关系程序级检查、辅助线文本本地 overlay plan 快路径；该类无歧义构造现在跳过 `figure_goal` / `figure_draw` / `figure_revision` LLM，只保留必要的点位 VLM，失败仍回退 LLM。新增回归 `test_build_overlay_plan_from_perpendicular_auxiliary_text`、`test_render_overlay_plan_constructs_point_on_perpendicular_with_distance`、`test_inspect_overlay_semantics_detects_wrong_perpendicular_construction`、`test_agent_service_uses_local_perpendicular_overlay_plan_without_draw_llm`；验证 `112 passed`、`git diff --check` 通过。
- 修正高分辨率 crop 下 `E` 点再次误吸附到右侧字母 `E` 笔画的问题：旧文字过滤使用固定面积阈值 900，高分辨率字母连通域面积约 1059，未被识别为标签。改为相对主几何连通域的紧凑小组件过滤，并保留旧的孤立字母 E 回归；真实图 2 crop 中 `E: raw=(656,288) -> snap=(662,291)`，不再跳到 `(693,293)`。新增回归 `test_snap_localized_points_ignores_large_letter_e_component_in_high_resolution_crop`；验证 `113 passed`、`git diff --check` 通过。

### Task 4.6.9：真实题图端到端验收

- [x] 使用真实后端服务、真实图片上传接口和真实 SSE 链路完成一次 HTTP 端到端验证，验证目录：`/tmp/studyhelper-e2e-overlay-20260525123140`。
- [ ] 使用 `tests/questions/几何-线段-全等.jpg` 第 16 题第（2）问做 Web 端上传测试。
- [ ] 端到端验收必须使用真实后端服务、真实前端 H5 页面、真实图片上传链路和真实 SSE 流；不能只用 mock LLM、单元测试或接口级模拟替代。
- [ ] 检查 SSE 事件包含完整主流程进度、`answer_end`、`reflexion_result`、绘图 attempt、`figure_result` 或非致命失败原因。
- [ ] 检查 `reflexion_result` 对用户可见，且能说明自检通过、修正、不可靠或失败原因。
- [ ] 检查解题文字中的辅助线意图和最终图中的辅助线是否一致。
- [ ] 检查最终图优先展示目标几何裁剪图，而不是整页题干图。
- [ ] 检查 `AE` / `EA` 延长方向与文字答案一致；若不一致，Observation 必须指出方向错误并触发 Revision。
- [ ] 检查 trace 文件记录每一步输出，能够复盘 Transparent Reflexion / Target Crop / Point Locate / Draw Plan / Render / Observation / Revision。
- [ ] 若真实模型输出质量差，优先优化 Figure Prompt、Goal Check 和 Observation，而不是增加代码级硬规则。

**验收：** Web 端可见文字解答和辅助线图；若图不准，trace 中能看到 Observation 和 Revision 的依据。只有该端到端验收通过，Story 4.6 才能标记完成。

**验证：** 手动 Web 端测试 + 后端日志 + trace 文件复核。

## 5. 验收标准

1. 主解题流程保持 Plan-and-Solve，不改成全局 ReAct。
2. 辅助线绘图子流程采用受限 ReAct，至少包含 Draw Plan、Render、Observation、Revision、Best Effort。
3. Draw Plan 前必须有 Goal Check，将辅助线目标整理成 `expected_auxiliary`、`layout_hint` 和 warnings。
4. `python:figure` 不再被 Prompt 或编排层禁止；非标准但可识别的绘图代码可以 best-effort 提取。
5. 有题图的几何题优先使用目标图裁剪 overlay；重画示意图只作为无法裁剪或无法定位时的 fallback。
6. Draw Plan 必须保留有向延长线语义，`AE` 和 `EA` 不可混用。
7. 结构化几何失败、辅助线抽取失败、校验失败都不能默认阻断 LLM 绘图 fallback。
8. Figure Agent 触发不能只退回关键词硬判；有辅助线原文时可直接触发，触发对象缺失或不完整时必须有 fallback 和 warning。
9. Observation 必须能表达程序级执行结果、图片质量和 `next_action`；启用语义检查时还要表达 `keep`、`missing`、`wrong`、`style_issues` 和延长线方向错误。
10. `answer_end` 后必须允许用户继续输入；透明自检结果通过 `reflexion_result` 追加展示，不能后台静默修改答案。
11. 后置反思路径必须移除；`pre_figure_reflexion_enabled` 只控制是否启用 Figure Agent 前的透明自检。
12. 绘图失败不发送全局 `error`，不回滚文字答案，不阻塞用户继续追问。
13. 每次绘图 attempt 都写入 trace，可复盘触发、辅助线原文、目标图裁剪、点位定位、Goal Check、Draw Plan、代码或 overlay plan、错误、Observation 和最终选择；透明自检也必须写入 trace。
14. 后续 `reflexion_result`、`figure_result`、warning、非致命失败事件必须携带 `message_id`，前端能挂回原 AI 气泡。
15. `tests/questions/几何-线段-全等.jpg` 第 16 题第（2）问完成端到端验收。
16. Sprint 3 聊天、图片上传、SSE、Markdown / KaTeX、`figure_result` 流程不回归。
17. 自动化测试全部通过但端到端验收未通过时，Sprint 4 仍视为未完成。
18. 所有需要 LLM/VLM 参与的反思、检查、裁剪定位和修正节点必须有配置开关；关闭时继续 best effort，不新增默认阻断。

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 生成图与证明割裂 | 用户看到的辅助线和文字不一致 | Vision 自检、Observation、Revision 和 trace 复盘；不靠代码穷举策略 |
| 透明自检与原答案冲突 | 用户困惑、图文不一致 | 自检结果必须显式展示；Figure Agent 使用「原答案 + 自检结果」并优先采纳修正版 |
| 整页题图导致辅助线不可读 | 用户看不到关键构造 | 优先截取目标几何图并输出放大后的裁剪图 overlay |
| `AE` / `EA` 延长方向画反 | 辅助线和文字答案不一致 | Draw Plan 使用有向 `ray`；Observation 检查方向错误并触发 Revision |
| Vision 点位定位偏差 | 辅助线端点偏移 | 优先使用稳定本地版面裁剪做 Point Locate；点位 Prompt 保持最小化；低置信度进入 Observation，不作为硬阻断 |
| LLM 绘图代码不稳定 | 语法错误、空白图或无图 | sandbox stderr 回传 Revision；最多 1 到 2 次修正；保留 best effort |
| 结构化旧逻辑继续拦截流程 | 一点抽取 / 校验问题就不画图 | 明确结构化模块降级为可选增强；测试覆盖失败后 fallback |
| 成本和延迟增加 | Web 等待变长 | `answer_end` 先释放输入；透明自检和 Figure Agent 后置；语义检查可配置 |
| 语义自检误判 | 好图被误修或差图被放行 | 自检只作为 soft signal；最终优先展示安全、非空白 best effort |
| Trace 数据过多 | 磁盘增长、排查困难 | 按 session / message 分目录；后续增加保留策略 |
| sandbox 安全风险 | 任意代码执行 | 继续使用现有隔离、无网络、超时和资源限制 |

## 7. 开工前置条件

1. Sprint 3 的 H5 聊天、图片上传、SSE、`figure_result` 链路可用。
2. Python sandbox 可执行 matplotlib 绘图代码。
3. `tests/questions/几何-线段-全等.jpg` 可用于真实题图验收。
4. Figure Agent 的质量目标是「可见并可复盘」，不是一次性解决所有辅助线绘图准确性问题。
