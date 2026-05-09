# Sprint 1 Retrospective: AI 编排层搭建

## Keep

- 使用 Dify 快速迭代 Prompt 和 Chatflow，适合 Sprint 1 验证 AI 编排链路。
- 用会话变量显式保存 `current_question/current_diagram/current_knowledge`，比依赖 LLM Memory 更稳定。
- 通过真实题图端到端验证，而不是只检查节点是否执行成功，及时发现了图形上下文丢失和错误推导污染。
- 将题图识别和解题推理解耦：识别节点看图，下游解题节点只处理文本上下文。

## Problem

- 初始设计让解题节点继续接收图片，职责不清，且多轮追问时不利于上下文稳定。
- `diagram_description` 曾混入角和、互余、互补等推导性内容，导致下游模型把错误推导当作已知条件。
- 识别节点输出的 JSON 在 LaTeX 反斜杠上不稳定，`json.loads` 失败后会丢失图形上下文。
- 任务 7 中的 Python 绘图执行最初容易被误解为 Dify 内部能力，但完整绘图闭环需要后端沙箱和文件服务。

## Try

- 后续为 `code_parse_question` 增加更明确的可观测日志或调试输出，便于快速发现解析回退。
- 建立小型真实题图回归集，每次修改 Prompt 后固定跑几何、代数、物理/化学、英语样例。
- 直接解答节点增加“定稿答案”后处理或评审节点，减少草稿式表达进入最终回复。
- Python 绘图能力按「模型生成代码 → 后端沙箱执行 → MinIO 存储 → 前端展示」拆分实现。

## Action Items

| 行动项 | 归属 | 状态 |
|--------|------|------|
| 后端实现 Python 绘图沙箱，执行 `python:figure` 代码并返回图片 URL | Epic 2.6 | 待办 |
| 前端识别 `python:figure` 代码块并提交后端沙箱展示图片 | Epic 4.4 | 待办 |
| 准备跨学科真实题图回归集 | 后续验证任务 | 待办 |
| 为直接解答输出增加质量检查或后处理策略 | 后续 Prompt 迭代 | 待办 |
| 将 `code_parse_question` 的解析容错规则纳入回归检查 | 后续测试任务 | 待办 |
