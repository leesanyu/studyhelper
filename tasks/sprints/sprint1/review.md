# Sprint 1 Review: AI 编排层搭建

## 结论

Sprint 1 已完成 AI 编排层核心闭环：Dify 本地环境、模型配置、图片上传识别、知识点提取、多轮引导、直接解答、新题切换和几何题上下文传递均已跑通。

最终发布的 Chatflow 版本：

| 字段 | 值 |
|------|-----|
| App ID | `c7888cbf-c784-40d5-9a0f-2478f4b735d2` |
| Workflow ID | `c063fc47-36cd-49fe-97de-825659d4d398` |
| 标记 | `识别解析容错` |
| 说明 | `code_parse_question` 修复 LaTeX 反斜杠导致的 JSON 解析失败 |

## 验收结果

| 验收项 | 结果 | 证据 |
|--------|------|------|
| Dify 本地后台可用 | 通过 | Dify 容器运行，API 可调用 |
| 模型配置可用 | 通过 | `qwen3.6-plus` 用于题目识别与解题节点 |
| 图片上传识别 | 通过 | Service API 上传 `tests/questions/几何-角度-线段.jpg` 后可触发工作流 |
| 题目识别输出 | 通过 | `code_parse_question.has_figure=true`，`diagram_description` 非空 |
| 图形上下文传递 | 通过 | 题图只进入「题目识别」节点，下游解题节点 `files=[]` |
| 直接解答正确性 | 通过 | 几何题最终关系输出为 $\angle DBE=90^\circ+\frac{1}{2}\angle C$ |
| Python 绘图执行 | 不纳入 Sprint 1 | Dify 仅生成绘图代码；执行、图片存储和 URL 返回转入后端沙箱 |

## 关键设计调整

1. 题图只进入「题目识别」节点，识别结果写入 `current_question/current_diagram/current_knowledge`。
2. 「直接解答」和「引导式解答」节点关闭 Vision，只消费纯文本上下文。
3. `diagram_description` 只描述题干和图片直接给出的点线角拓扑，不写推导结论。
4. `code_parse_question` 增加 LaTeX 反斜杠容错，避免 `\angle`、`\circ` 破坏 JSON 解析。
5. Python 绘图代码执行不放在 Dify 内部，统一转入 FastAPI 独立沙箱。

## 已知风险

| 风险 | 影响 | 后续处理 |
|------|------|----------|
| 复杂几何题直接解答仍可能偏长 | 影响展示质量 | 后续用更多真实题图继续压缩定稿表达 |
| 跨学科测试样本不足 | 覆盖面有限 | 建立回归题库后补充数学、物理/化学、英语验证 |
| Python 绘图未形成运行闭环 | 前端暂不能直接展示生成图 | Sprint 2 实现后端沙箱，Epic 4.4 完成前端展示 |

## Sprint 1 交付物

- 最终版 Dify Chatflow
- Prompt 文档：
  - `docs/prompts/node_a_question_recognition.md`
  - `docs/prompts/node_b_knowledge_extraction.md`
  - `docs/prompts/node_c_socratic_tutor.md`
  - `docs/prompts/node_d_direct_answer.md`
- Sprint 文档：
  - `tasks/sprints/sprint1/planning.md`
  - `tasks/sprints/sprint1/review.md`
  - `tasks/sprints/sprint1/retrospective.md`
- 经验教训：
  - `tasks/lessons.md`
