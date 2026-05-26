


这是一份为你量身定制的**《Study Helper 智能学习助手 开发实施计划书》**。作为软件工程师，你可以直接将这份文档作为项目的 README 或者导入到你的项目管理工具（如 Jira、Notion、Teambition）中作为 Epics 和 Tasks。

---

# Study Helper 智能学习助手 - 开发实施计划书 (MVP 阶段)

## 1. 项目概述
*   **产品定位：** 专注于辅助中小学生学习的 AI 智能体应用，提供苏格拉底式的答疑、个性化薄弱点强化及日常练习。
*   **产品形态：** 跨端应用（前期 H5 Web 端跑通全链路，中期上线微信小程序，后期打包 App）。
*   **核心策略：** “重 AI 编排，轻本地数据”。前期不自建庞大题库，利用大模型泛化能力和向量库检索历史数据。

## 2. 技术栈选型
| 模块 | 技术选型 | 备注说明 |
| :--- | :--- | :--- |
| **前端架构** | Uni-app (Vue 3) / Taro (React) | 跨端框架，一套代码编译 H5 和微信小程序 |
| **公式与渲染** | `markdown-it` + `KaTeX` / `MathJax` | 核心难点：解析大模型返回的 LaTeX 数学公式 |
| **AI 编排层** | FastAPI Agent（Plan-and-Solve + Reflexion） | 自建规划层、工具层、执行层和反思层，Prompt 纳入代码版本管理 |
| **业务后端** | Python (FastAPI) | 承担用户鉴权、数据持久化、请求中转分发 |
| **数据库** | PostgreSQL + `pgvector` 扩展 | 关系型数据存用户/记录，向量存储用于相似题检索 |
| **底层大模型** | `qwen-vl-max` / `qwen3.6-plus` | 视觉模型负责题图识别和复核，文本模型负责规划、知识点提取和解题 |

---

## 3. 核心业务数据流转设计

### 3.1 核心答疑链路（拍照 -> 解析 -> 反馈）
1.  **用户**通过前端拍照/传图上传。
2.  **FastAPI** 接收图片，完成校验/压缩，保存为 `asset_id`，用于预览、历史追溯和后续 Agent 工具读取。
3.  **Agent 规划层**根据用户消息、图片摘要和当前会话上下文决定教学策略与工具调用。
4.  **Agent 工具层**按计划执行 `process_question` 和 `extract_knowledge`，将题干、图形关系和知识点写入会话上下文。
5.  **Agent 执行层**根据策略生成文字解题，前端通过 SSE（Server-Sent Events）接收实时 `delta`、`thinking`、`tool_result`、`figure_result` 等事件。
6.  **用户**点击反馈按钮：
    *   **`<我不甚理解>`**：发送自然语言反馈，Agent 规划层切换为 `step_breakdown` 策略。
    *   **`<我会了>`**：发送自然语言反馈，Agent 规划层切换为 `summarize_and_similar` 策略。

### 3.2 几何辅助线绘图方案
*   **主解题流程：** 继续采用 Plan-and-Solve。规划层决定是否调用题目识别和知识点提取，工具层整理题图观察，执行层生成文字解题和辅助线意图。
*   **绘图子流程：** 辅助线绘图采用受限 ReAct。有明确辅助线文本时直接启动 Figure Agent，跳过额外 Trigger LLM；Goal Check、VLM 目标裁剪、语义检查和 Revision 都有配置开关。关闭检查或修正时走本地轻量回退或展示 best effort，不阻断文字答案和已有图。
*   **结构化增强：** `GeometrySceneCandidate`、`auxiliary_extractor`、`geometry_validator` 和 `geometry_renderer` 保留为可选增强能力；失败时只产生 warning / Observation，不作为默认阻断。
*   **展示侧：** 后端继续通过 `figure_result` SSE 事件推送图片。文字答案结束后先发送 `answer_end`，前端允许继续输入；后置图片、warning 和非致命失败事件携带 `message_id`，归属原 AI 气泡。
*   **复盘侧：** 每次提交试题保存 trace，包含题目识别、知识点、Solve 输出、触发判断、Goal Check、绘图代码、sandbox 结果、Observation、Revision 和最终图片。

---

## 4. 实施路径 (Action Plan)

计划分为 4 个 Sprint (迭代周期)，预计耗时 4-6 周。

### Sprint 1: AI 引擎与基础设施搭建（已闭环）
*   [x] **任务 1.1**：本地 Docker 环境可用。
*   [x] **任务 1.2**：部署开源版 Dify。
*   [x] **任务 1.3**：在 Dify 中配置模型凭证。
*   [x] **任务 1.4（核心）**：在 Dify 中建立 Chatflow，跑通图片识别、知识点提取、多轮引导、直接解答和新题切换。
*   [x] **边界确认**：Python 绘图执行不放在 Dify 内部，转入后端沙箱和前端展示链路。

### Sprint 2: 业务后端与数据库搭建（已闭环）
*   [x] **Story 2.1**：初始化 FastAPI 工程，完成项目结构、路由、配置管理、日志、异常处理和健康检查。
*   [x] **Story 2.2**：设计并创建 PostgreSQL 数据库表：`users`（匿名占位）、`chat_sessions`、`chat_messages`、`user_tags_history`、`assets`，并通过 Alembic 管理迁移。
*   [x] **Story 2.3**：实现流式聊天接口 `/api/v1/chat/completions`，返回 SSE，并在后续 Agent 重构中切换为自建编排。
*   [x] **Story 2.4**：实现图片上传接口，保存本地或 MinIO 预览资产，返回后续聊天可引用的 `asset_id`。
*   [x] **Story 2.5**：实现对话管理：创建/续接会话、获取历史消息、会话列表、同步新题目/继续追问/直接解答状态。
*   [x] **Story 2.6**：实现 Python 绘图代码沙箱，隔离执行 `python:figure`，生成图片并返回 `asset_id` 或 URL。
*   [x] **Story 4.5**：建立最小核心答疑回归集，覆盖真实题图、上传、会话、Agent 编排和沙箱关键路径。

### Sprint Refactor: 后端 Agent 架构重构（已完成）
*   [x] **R.1**：搭建 Agent 基础设施（openai SDK、LLM 客户端、6 场景模型配置）。
*   [x] **R.2**：实现 Agent 工具层（process_question + extract_knowledge）。
*   [x] **R.3**：实现规划层（plan）和执行层（solve）。
*   [x] **R.4**：实现反思层（正则 Level 1 + LLM Level 2）和 Agent 编排服务。
*   [x] **R.5**：重写 ChatService 和文件上传（移除 Dify 依赖）。
*   [x] **R.6**：清理 Dify 代码依赖（删除 dify.py、相关字段、Alembic 迁移）。
*   [x] **R.7**：更新 Docker 配置（移除 Dify 环境变量，添加 LLM API 配置）。
*   [x] **R.8**：更新文档（framework.md、planning.md）。

### Sprint 3: 跨端前端搭建与核心答疑闭环（已进入 Sprint 4 前置状态）
*   [x] **Story 3.1**：初始化 Uni-app (Vue 3) 项目，搭建基础 UI 框架（首页、聊天页、历史页 TabBar）。
*   [x] **Story 3.2**：实现聊天对话页：消息气泡列表 + 输入框 + 发送按钮。
*   [x] **Story 3.3 (难点)**：实现 SSE 实时流式输出、`thinking` 和 `tool_result` 进度事件。
*   [x] **Story 3.4 (难点)**：集成 Markdown 和 KaTeX 渲染。
*   [x] **Story 3.5**：实现拍照/选图上传，聊天请求通过 `asset_ids` 传递图片。
*   [x] **Story 3.6**：图片预览：上传后在聊天框中展示图片缩略图。
*   [x] **Story 3.7 + 4.4**：实现 `python:figure` 代码块识别和 `figure_result` 被动渲染。
*   [x] **Story 4.3**：前端通过自然语言反馈触发 Agent 的分步拆解和总结相似题策略。

### Sprint 4: 几何辅助线绘图 Agent（当前执行）
*   [ ] **Story 4.6**：几何辅助线正确绘制。
    *   [x] **Task 4.6.0**：同步设计与计划，明确主流程继续 Plan-and-Solve，辅助线绘图子流程采用 Figure Agent ReAct。
    *   [x] **Task 4.6.1**：解除现有硬阻断，移除禁止 `python:figure` 的 Prompt，结构化抽取 / 校验 / 渲染失败时继续尝试 LLM 绘图 fallback。
    *   [x] **Task 4.6.2**：新增 Figure Agent 首版编排，包含触发判断、Goal Check、Draw Plan、sandbox Render、最小 trace、attempt 记录和 `figure_result` 输出。
    *   [x] **Task 4.6.3**：补齐程序级 Observation 与 Revision 闭环，把 sandbox 错误、空白图和 `next_action` 交回 LLM 修正。
    *   [x] **Task 4.6.4**：增加可选 Vision 语义检查，将缺失辅助线、错误构造和建议修正转成 soft signal。
    *   [x] **Task 4.6.5**：扩展 trace 文件，每次提交题目保存识别、解题、Goal Check、绘图代码、执行结果、Observation、Revision 和最终图片。
    *   [x] **Task 4.6.6**：确认前端 SSE 兼容，`answer_end` 后输入可用，后置 `figure_result`、warning 和非致命失败按 `message_id` 回填，不阻塞追问。
    *   [x] **Task 4.6.7**：补齐自动化回归，覆盖图片题流程、Draw Plan fallback、Revision、best effort 和非致命失败。
    *   [x] **Task 4.6.7a**：优化 Figure Agent 模型调用链，辅助线文本跳过 Trigger LLM，Goal / VLM 裁剪 / 语义检查 / Revision 节点均支持配置开关。
    *   [ ] **Task 4.6.8**：使用 `tests/questions/几何-线段-全等.jpg` 第 16 题第（2）问完成真实 Web 端到端验收；自动化测试通过但该验收未通过时，Story 4.6 不算完成。

---

## 5. 前期开发核心避坑指南 (Tips)

1.  **公式渲染的坑：** 大模型吐出的公式格式经常不统一。**对策：** Agent Prompt 统一要求行内公式使用 `$...$`，块级公式使用 `$$...$$`；前端 Markdown/KaTeX 渲染层只做必要清洗，不承担语义修正。
2.  **几何题识别污染：** 题图识别如果输出推导结论，会污染后续解题。**对策：** 识别层只输出直接可见事实和题干关系，推导关系必须留给解题层。
3.  **辅助线绘图过度限制：** 辅助线方式难以穷举，结构化抽取或校验一旦成为硬闸门，就会导致有解题文字但没有图。**对策：** Sprint 4 改为「主流程 Plan-and-Solve + 辅助线绘图 ReAct」，结构化模块只做增强；安全可执行时优先展示 best effort。对原图 overlay 的点位漂移，采用「VLM 粗定位 + 本地像素吸附」修正坐标，但吸附失败只记录 warning，不阻断绘图。
4.  **响应耗时：** 多模态图片解析和几何题求解耗时较长。**对策：** 后端保持实时 SSE，先发送 `message_start`、`thinking`、`tool_result`，再流式发送 `delta` 和后置 `figure_result`。

---

**下一步建议：**
Sprint 1、Sprint 2、Sprint Refactor 和 Sprint 3 已为当前工作提供后端 Agent、图片上传、SSE、沙箱与前端 `figure_result` 展示链路。当前进入 **Sprint 4**，按 `tasks/sprints/sprint4/planning.md` 实施「几何辅助线绘图 Agent」：先解除现有硬阻断，再接入 Figure Agent 的 Trigger / Goal Check / Draw Plan / Render / Observation / Revision 闭环，最后用 `tests/questions/几何-线段-全等.jpg` 第 16 题第（2）问完成真实 Web 端到端验收。该端到端验收是最终完成标准，不能被 mock 测试或接口级模拟替代。
