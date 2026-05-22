# Sprint Refactor：从 Dify Chatflow 重构为 AI Agent

**状态：✅ 已完成（2026-05-20）**

## Context

当前 StudyHelper 后端通过 Dify Chatflow 编排 AI 逻辑（15 个节点：IF/ELSE + Question Classifier + 4 个 LLM + 代码解析 + 变量读写），这是工作流思维——预定义分支、硬编码路由、状态机驱动。

产品核心是苏格拉底式教学 AI，本质是一个智能体：有记忆、能自主决策、能使用工具。工作流思维在以下方面成为束缚：
- 新增反馈分支需要改 Classifier + 新增 LLM 节点 + 改路由，改动大
- `inputs.mode` 传入 Dify 后未被任何节点消费，集成脆弱
- 调试和迭代 Prompt 需要在 Dify UI 中操作，脱离代码版本控制
- 后端已承担所有重活（沙箱、持久化、文件管理），Dify 是多余的中间人

**目标**：去掉 Dify，在 FastAPI 中实现分层 Agent 架构，采用 Plan-and-Solve + Reflexion 变体。

## 架构设计

### 架构变化

```
重构前：前端 → Nginx → FastAPI → Dify(15节点Chatflow) → LLM API
重构后：前端 → Nginx → FastAPI(Agent 分层架构) → LLM API
```

### 部署架构（重构后）

```
┌─ Docker Compose (studyhelper) ─────────────────────────────┐
│                                                             │
│  nginx ──── 静态文件(SPA) + API代理 + SSE超时               │
│    │                                                        │
│  backend ── FastAPI + Agent(输入/规划/执行/反思)             │
│    │         ├── LLM API (通义千问，外部，非容器)            │
│    │         ├── Docker SDK → 按需启动 sandbox 容器          │
│    │         └── business_db / redis / minio (容器内)        │
│    │                                                        │
│  business_db (PostgreSQL + pgvector)                        │
│  redis (缓存/限流)                                          │
│  minio (对象存储)                                           │
│                                                             │
│  code_sandbox (按需启动，无网络，只读，资源限制)              │
│                                                             │
└─────────────────────────────────────────────────────────────┘

删除：dify/ (11个容器 + 源码目录)
网络：studyhelper_net 改为普通 bridge 网络（不再需要与 Dify 共享）
```

**保留的容器及理由：**

| 容器 | 理由 |
|------|------|
| nginx | Sprint 3 前端 SPA 路由 + API 代理 + SSE 300s 超时配置 |
| backend | Agent 核心服务，调用 LLM API + 编排工具 + 流式输出 |
| business_db | 业务数据持久化（会话、消息、资产） |
| redis | 缓存、限流、后续会话状态缓存 |
| minio | 图片和沙箱产物的对象存储 |
| code_sandbox | `render_figure` 工具的执行引擎，安全隔离 |

**删除的容器：** dify-api、dify-web、dify-worker、dify-worker_beat、dify-nginx、dify-plugin_daemon、dify-sandbox、dify-redis、dify-db_postgres、dify-weaviate、dify-ssrf_proxy

### 开发阶段 vs 生产部署

| 阶段 | backend 运行方式 | 说明 |
|------|-----------------|------|
| **开发阶段（当前）** | 宿主机直接运行 `uvicorn` | 调试 Prompt、迭代 Agent 逻辑方便，改代码即生效，不用重建镜像；连接 business_db/redis/minio 使用 localhost 端口映射 |
| **生产部署** | Docker 容器 | 一键 `docker compose up`，环境一致，资源隔离；需要 Docker Socket 挂载以启动 sandbox |

开发阶段启动命令：
```bash
# 基础设施（数据库、缓存、对象存储）
docker compose up -d business_db redis minio

# 后端（宿主机）
cd backend && PYTHONPATH=/tmp/studyhelper-pydeps:. uvicorn app.main:app --reload --port 8000

# 沙箱镜像（一次性构建）
docker compose build code_sandbox
```

生产部署：
```bash
docker compose --profile backend --profile frontend up -d
```

### Agent 架构：Plan-and-Solve + Reflexion

```
┌─────────────────────────────────────────────────────────────┐
│                   规划层 (Plan)                              │
│  LLM 分析用户消息，输出结构化计划：                            │
│  {question_type, strategy, tool_calls: [...],               │
│   need_deep_reflexion: bool}                                 │
│                                                             │
│  question_type: definition / logical_calculation /           │
│    homework_help / direct_answer_request / continue_dialogue │
│  strategy: socratic_guide / step_breakdown / direct_answer / │
│    summarize_and_similar / knowledge_lookup                  │
│  tool_calls: ["process_question", "extract_knowledge", ...]  │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   工具执行 (Tool Execution)                   │
│  编排层按计划顺序执行工具：                                    │
│  - process_question: 多模态题目解析（图片/文字→结构化）        │
│  - extract_knowledge: 知识点提取（题干→标签+难度）            │
│  编排层执行工具，收集结果，更新会话状态                        │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   执行层 (Solve)                             │
│  LLM 根据策略 + 工具结果生成最终回复                          │
│  strategy 决定输出行为：                                      │
│  - socratic_guide: 反问、启发，不直接给答案                   │
│  - step_breakdown: 更细致的逐步引导                           │
│  - direct_answer: 完整过程+最终答案                           │
│  - summarize_and_similar: 总结要点+相似题                     │
│  输出缓冲，不立即流式发送                                     │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                 反思与修正层 (Reflexion)                      │
│  两级检查：正则必过，LLM 按需触发                             │
│  一级（正则，每轮必过）：                                     │
│  - 引导/拆解模式：是否泄露了最终答案？                        │
│  - 总结/出题模式：要点≥2条？相似题不含答案？                  │
│  二级（LLM，按需触发）：                                     │
│  - 触发条件：difficulty=="困难" 或 用户表达不满               │
│  - 检查计算步骤有无逻辑跳跃，修正后输出                       │
│  修正后的内容 → 流式发送给学生                                │
└─────────────────────────────────────────────────────────────┘
```

**四层分离，职责明确**：规划层决定"做什么"，工具执行层收集信息，执行层决定"怎么说"，反思层保证"说对了"。

### 关键设计决策

1. **Plan-and-Solve 四层分离**：规划层（LLM，决定做什么+调用什么工具）→ 工具执行层（编排层代码，按计划顺序执行）→ 执行层（LLM，根据策略和工具结果生成回复）→ 反思层（检查修正）。`render_figure` 不是规划层调度的工具，而是编排层对执行层输出中 `python:figure` 代码块的后处理。

2. **规划层是核心差异化**：不是直接给答案，而是先分析"学生需要什么类型的帮助"。但学生有权在任何时候要求直接答案——无论是首次提问还是引导中途，规划层必须将 strategy 切换为 `direct_answer`。

3. **反思层两级检查：正则必过，LLM 按需触发**：
   - 一级（正则，每轮必过，零 LLM 开销）：
     - 引导/拆解模式：正则匹配最终答案泄露模式（如"答案是 X"、"所以 X=5"），检测到则删除答案部分并替换为引导性提示
     - 直接解答模式：确认输出中包含"最终答案"标注，缺失则追加提示
     - 总结/出题模式：确认要点不少于 2 条、相似题不含答案
     - **取舍**：正则只能覆盖显式泄露模式，无法拦截"这个角等于 60°"等隐性泄露。扩展正则会误杀直接解答模式下的正确输出，误杀比漏报更严重。漏报的代价是引导中偶尔泄露答案，学生在后续追问中会自行判断，下轮规划层也会调整 strategy
   - 二级（LLM，按需触发，使用 `llm_model_reflexion`）：
     - 触发条件（满足任一）：`extract_knowledge` 返回 `difficulty=="困难"`（数据已有，零成本判断）；或规划层从用户消息中识别不满信号，在输出中设置 `need_deep_reflexion=true`
     - LLM 自检验证计算步骤有无逻辑跳跃，检测到错误则修正
   - 大部分轮次只走正则，无额外延迟和 Token 开销；仅在难题或用户不满时付出一次额外调用的代价

4. **图片预处理为摘要**：编排层将图片转换为摘要文本（如"[用户上传了一张包含数学题目的图片]"）传入 LLM messages，LLM 据此决定是否调用 `process_question`。图片 base64 只在工具执行时使用，不传给主 LLM。

5. **先缓冲再流式**：执行层完整输出先缓冲，经反思层检查/修正后，再逐段流式发送给学生（打字机效果）。反思修正对用户透明，用户只看到修正后的内容。TTFT 延迟控制：一级正则检查为毫秒级，二级 LLM 自检仅在难题/不满时触发（可配更轻量模型 `llm_model_reflexion`），大部分轮次无额外延迟。

6. **会话状态由 Agent 自行管理**：`current_question`/`current_knowledge`/`current_diagram` 保留在 `ChatSession` 表中，由编排层在工具调用后更新。`context_ready` 不单独建列，由 `current_question IS NOT NULL` 推导——当前模型已有此字段，无需冗余。

7. **Memory 从数据库加载**：每次调用 LLM 时，从 `ChatMessage` 表加载最近 20 条历史作为消息列表传入，替代 Dify 的 per-node Memory 机制。

### Agent 工具定义

规划层调度的工具（由编排层按计划顺序执行）：

| 工具 | 说明 | 规划层决策依据 |
|------|------|-------------|
| `process_question` | 多模态题目解析：图片/文字→题干文本+学科+图形描述 | 用户上传了图片（messages 中有图片摘要）或提出了新题目 |
| `extract_knowledge` | 知识点提取：题干→知识点标签+难度+年级 | 需要知识点上下文来指导教学策略 |

编排层后处理步骤（非规划层调度）：

| 步骤 | 说明 | 触发条件 |
|------|------|----------|
| `render_figure` | 几何图形渲染：matplotlib 代码→图片 URL | 执行层输出中包含 `python:figure` 代码块 |

### 对话流程示例

**场景：学生上传几何题图片**

```
学生：[上传一张三角形求角度的题图]

规划层：question_type="logical_calculation", strategy="socratic_guide",
        tool_calls=["process_question", "extract_knowledge"]
工具执行：process_question(图片) → 题干="在△ABC中..." + 学科="初中数学" + 图形描述
         extract_knowledge(题干) → 知识点=["三角形内角和","角度计算"]
执行层：Socratic引导输出 "这道题涉及到三角形内角和..."（含 python:figure）
反思层：规则检查 → 未泄露答案 ✓
后处理：解析 python:figure → render_figure → figure_result

学生看到：
  "这道题涉及到三角形内角和的一个重要性质！
   思路提示：三个内角加起来等于多少？
   [几何辅助图]
   引导提问：如果已知两个角，第三个角怎么求？"
```

**场景：学生说"我还是不懂"**

```
学生：我还是不太理解

规划层：question_type="continue_dialogue", strategy="step_breakdown",
        tool_calls=[]（无需工具，已有上下文）
工具执行：无
执行层：更细致的逐步引导
反思层：规则检查 → 未泄露答案 ✓

学生看到：
  "没关系，我们换个角度来想。第一步，先看题目给了哪些已知条件..."
```

**场景：学生说"我会了"**

```
学生：我理解了！

规划层：question_type="continue_dialogue", strategy="summarize_and_similar",
        tool_calls=[]（无需工具）
工具执行：无
执行层：总结要点 + 生成相似题
反思层：检查相似题是否泄露答案 ✓

学生看到：
  "太棒了！总结一下这道题的关键：
   1. 三角形内角和为180°
   2. 已知两角求三角用减法
   来试试这道相似题：..."
```

### 前端接口契约变化

SSE 事件类型不变（message_start/delta/message_end/error），新增 `figure_result` 事件。但事件 data 格式会变化：删除 `dify_message_id`/`conversation_id`，替换为 Agent 原生字段。

重构后 SSE 事件 data 格式：

| 事件 | data 格式 | 变化说明 |
|------|-----------|----------|
| message_start | `{"session_id": "..."}` | 删除 `conversation_id`/`dify_message_id` |
| delta | `{"session_id": "...", "text": "..."}` | 不变 |
| message_end | `{"session_id": "...", "message_id": "..."}` | 删除 `dify_message_id`/`conversation_id`，新增 `message_id` |
| error | `{"code": "...", "message": "..."}` | 不变 |
| figure_result | `{"asset_id": "...", "image_url": "..."}` | **新增**；在所有 delta 之后、message_end 之前发送。前端约定：收到 `figure_result` 后，将之前 delta 中对应的 `python:figure` 代码块替换为图片渲染 |

## 复用 / 删除 / 新增

### 复用清单

| 组件 | 处置 |
|------|------|
| sandbox.py | 完全复用 |
| assets.py / storage.py | 完全复用 |
| messages.py | 复用，删除 `dify_message_id` 相关代码 |
| sessions.py | 复用，删除 `dify_conversation_id` 相关代码 |
| SSE 路由 / SimpleSSEStreamingResponse | 完全复用 |
| 数据库模型 / 迁移 | 完全复用 |
| 4 个 Prompt | 迁移为代码中的分层 Prompt 模板 |

### 删除清单

| 组件 | 文件 | 处置 |
|------|------|------|
| DifyClient | `backend/app/services/dify.py` | 删除整个文件 |
| DifyChatService | `backend/app/services/chat.py` | 重写为 AgentChatService |
| DifyUploadClient | `backend/app/services/files.py` | 重写，图片不再上传到 Dify |
| Dify 配置项 | `backend/app/core/config.py` | 删除 `dify_api_url`/`dify_api_key`，新增 LLM 配置 |
| Dify 依赖注入 | `backend/app/api/deps.py` | 替换 DifyClient 构造为 LLM Client |
| Dify 相关测试 | `backend/tests/test_dify_client.py` | 删除 |
| Dify 回归测试 | `backend/tests/test_regression_chatflow_modes.py` | 重写为 Agent 回归测试 |
| Dify Chat 测试 | `backend/tests/test_chat_service.py` | 重写为 AgentChatService 测试 |
| Dify 文件测试 | `backend/tests/test_files_service.py` | 重写，移除 DifyUploadClient mock |
| Dify 源码目录 | `dify/`（git clone） | 删除目录 |
| Dify Docker 容器 | 11 个 dify-* 容器 | 停止并删除 |
| Dify Docker 镜像 | dify-api:1.14.0 等 | 删除 |
| Dify compose 配置 | `docker/.env` 中 DIFY_* 配置 | 删除 |
| setup.sh 中 Dify 步骤 | `scripts/setup.sh` | 删除步骤 3/6（Dify 部署和验证） |
| studyhelper_net 依赖 | `docker/docker-compose.yml` | 移除与 Dify 互联的注释和配置 |

### 数据库字段处理

直接删除 `dify_conversation_id`、`dify_message_id`、`dify_file_id` 三列，新增 Alembic 迁移。项目刚开始，无需兼容历史数据。

### 新增清单

新增文件统一放在 `backend/app/agent/` 目录下，与现有 `backend/app/services/` 平级：

| 组件 | 说明 |
|------|------|
| backend/app/agent/__init__.py | 包初始化 |
| backend/app/agent/llm_client.py | OpenAI 兼容 LLM 客户端（流式 + vision） |
| backend/app/agent/prompts.py | 规划层 Prompt + 执行层 Prompt（苏格拉底导师）+ 工具 Prompt（题目识别、知识点提取） |
| backend/app/agent/tools.py | 工具定义（process_question, extract_knowledge）；render_figure 由编排层直接调用沙箱服务，不在工具定义中 |
| backend/app/agent/reflexion.py | 反思层：规则检查 + LLM 深度自检 |
| backend/app/agent/service.py | Agent 编排服务：分层调度、Memory 加载、会话状态管理 |

## Story 分解

### Story R.1: 实现 OpenAI 兼容 LLM 客户端
- 封装 `backend/app/agent/llm_client.py`：基于 `openai` SDK（AsyncOpenAI）调用 OpenAI 兼容 API
  - 选择 openai SDK 而非自建 httpx 封装的理由：SDK 内置流式 SSE 解析、指数退避重试、连接池复用、类型提示，通义千问等主流厂商 OpenAI 兼容端点官方支持；自建 httpx 封装需手动处理流式解析和重试，维护成本高
- 支持三种调用模式：
  - **流式聊天**：`stream_chat(messages) → AsyncIterator[StreamEvent]`，返回 delta 文本
  - **非流式聊天**：`chat(messages, response_format?) → ChatResponse`，用于规划层、工具调用和反思层（不需要流式）
  - **Vision 聊天**：`stream_chat(messages_with_image)`，messages 中 content 支持 image_url 类型（base64 编码）
  - 注：当前架构不需要 OpenAI tool_calling（规划层输出结构化 JSON 由编排层解析，不是 LLM 自主决定工具调用）。若未来需要 ReAct 模式再扩展
- **JSON Mode**：规划层、知识点提取、题目标准化等需要结构化输出的场景，调用 `chat()` 时传入 `response_format={"type": "json_object"}`，由 API 层面保证输出合法 JSON，省去编排层中的 JSON 修复逻辑
- 配置项（`config.py`）集中管理所有模型，采用**默认供应商 + 按模型可选覆盖**的设计：

  **默认供应商**（所有模型共享，必填）：

  | 配置项 | 默认值 | 说明 |
  |-------|--------|------|
  | `llm_api_url` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 默认 OpenAI 兼容 API 端点 |
  | `llm_api_key` | *(必填)* | 默认 API Key |

  **模型配置**（每个场景独立，模型名必填，url/key 可选覆盖）：

  | 配置项 | 默认值 | 场景 |
  |-------|--------|------|
  | `llm_model_planning` | `qwen3.6-plus` | 规划层：题目分类+策略选择 |
  | `llm_model_planning_url` | *None* | 覆盖该模型的 API 端点，None 则用默认 |
  | `llm_model_planning_key` | *None* | 覆盖该模型的 API Key，None 则用默认 |
  | `llm_model_question_parse` | `qwen3.6-plus` | 题目标准化：文字→结构化题干 |
  | `llm_model_question_parse_url` | *None* | 同上 |
  | `llm_model_question_parse_key` | *None* | 同上 |
  | `llm_model_solving` | `qwen3.6-plus` | 执行层：教学回复生成 |
  | `llm_model_solving_url` | *None* | 同上 |
  | `llm_model_solving_key` | *None* | 同上 |
  | `llm_model_reflexion` | `qwen3.6-plus` | 反思层 LLM 自检（仅难题/不满时触发） |
  | `llm_model_reflexion_url` | *None* | 同上 |
  | `llm_model_reflexion_key` | *None* | 同上 |
  | `llm_model_vision` | `qwen-vl-max` | 题目识别：图片→结构化题干 |
  | `llm_model_vision_url` | *None* | 同上 |
  | `llm_model_vision_key` | *None* | 同上 |
  | `llm_model_knowledge` | `qwen3.6-plus` | 知识点提取：题干→标签+难度 |
  | `llm_model_knowledge_url` | *None* | 同上 |
  | `llm_model_knowledge_key` | *None* | 同上 |

  **设计说明**：
  - 最简配置只需 8 项：`llm_api_url` + `llm_api_key` + 6 个模型名（所有模型用同一供应商）
  - 按需覆盖：某模型想用不同供应商时，设对应的 `_url` + `_key` 即可，其余模型不受影响
  - 例：执行层想用 DeepSeek → 设 `LLM_MODEL_SOLVING=deepseek-chat` + `LLM_MODEL_SOLVING_URL=https://api.deepseek.com/v1` + `LLM_MODEL_SOLVING_KEY=sk-xxx`，其他模型仍走通义千问
  - LLM 客户端内部解析逻辑：`url = model_xxx_url or llm_api_url`，`key = model_xxx_key or llm_api_key`

- 内置重试：openai SDK 自带指数退避重试（`max_retries=2`，仅对 5xx / 网络超时重试，4xx 不重试），无需自建重试逻辑
- StreamEvent 类型定义：`TextDelta(text)` / `StreamEnd()`
- 验证：可流式调用 qwen3.6-plus 并收到 delta 输出；可非流式调用并收到结构化 JSON 响应（JSON Mode）；可发送图片 base64 并收到识别结果
- **交付物**：LLM 客户端 + StreamEvent 类型 + 单元测试（mock openai SDK）
- **工作量**：1 天

### Story R.2: 实现 Agent 工具定义
- 工具定位：**编排层按规划层计划显式调用的子函数**。规划层决定调用哪些工具、以什么顺序，编排层按计划执行。`render_figure` 不在此列，它是编排层对执行层输出中 `python:figure` 代码块的后处理。
- 两个工具函数：
  - `process_question(image_base64: str | None, text: str | None) → QuestionResult`：
    - 有图片时调用视觉模型（`llm_model_vision`，图片→结构化题干），纯文字时调用题目标准化模型（`llm_model_question_parse`，文字→结构化题干），保证有图无图输出统一结构，后续 `extract_knowledge` 输入对齐
    - Prompt 迁移自 Node A
    - 返回：`{subject, question_text, has_figure, diagram_description, question_count}`
    - 返回 JSON Schema 示例：
      ```json
      {
        "subject": "初中数学",
        "question_text": "在△ABC中，∠A=60°，∠B=50°，求∠C的度数",
        "has_figure": true,
        "diagram_description": "三角形ABC，顶点A、B、C顺时针排列，∠A标注60°，∠B标注50°",
        "question_count": 1
      }
      ```
  - `extract_knowledge(question_text: str, subject: str) → KnowledgeResult`：
    - 调用知识点模型（`llm_model_knowledge`），Prompt 迁移自 Node B
    - 返回：`{subject, knowledge_points[], difficulty, grade_level}`
    - 返回 JSON Schema 示例：
      ```json
      {
        "subject": "初中数学",
        "knowledge_points": ["三角形内角和", "角度计算"],
        "difficulty": "简单",
        "grade_level": "七年级"
      }
      ```
- 验证：两个工具可独立调用并返回正确结果
- **交付物**：工具函数 + 返回类型定义 + 单元测试
- **工作量**：1 天

### Story R.3: 实现规划层和执行层
- **Prompt 模板变量约定**（适用于所有层级）：
  - 使用 Python f-string 或 `str.format_map()` 做变量插值，语法为 `{variable_name}`
  - Dify 的 `{{#context#}}` / `{{#sys.query#}}` 等模板语法全部迁移为 Python 变量
  - 变量来源分两类：
    - **会话变量**：从 `ChatSession` 表加载（`current_question`/`current_diagram`/`current_knowledge`）
    - **运行时变量**：从编排层传入（`user_message`/`image_summary`/`tool_results`/`strategy`）
  - 模板文件统一放在 `backend/app/agent/prompts.py`，每个 Prompt 为一个函数，返回组装好的 messages 列表
- **规划层**（非流式，1 次 LLM 调用）：
  - 输入：用户消息 + 图片摘要（如有）+ 对话历史 + 当前题目上下文（如有）
  - Prompt：分析题目类型和教学策略，输出 JSON `{question_type, strategy, tool_calls, need_deep_reflexion}`
  - question_type：`definition` / `logical_calculation` / `homework_help` / `direct_answer_request` / `continue_dialogue`
  - strategy：`socratic_guide` / `step_breakdown` / `direct_answer` / `summarize_and_similar` / `knowledge_lookup`
  - tool_calls：需要执行的工具列表，如 `["process_question", "extract_knowledge"]`，已有上下文时为 `[]`
  - 规划层输出不流式传输给学生
  - **规划层输出 JSON Schema 示例**：
    ```json
    {
      "question_type": "logical_calculation",
      "strategy": "socratic_guide",
      "tool_calls": ["process_question", "extract_knowledge"],
      "need_deep_reflexion": false
    }
    ```
  - **JSON 容错**：规划层调用 LLM 时启用 JSON Mode（`response_format={"type": "json_object"}`），由 API 层面保证输出合法 JSON。解析失败（极端情况如 API 不支持 JSON Mode）则 fallback 为默认策略 `{question_type: "continue_dialogue", strategy: "socratic_guide", tool_calls: [], need_deep_reflexion: false}`
  - **图片处理约定**：编排层将图片预处理为摘要文本（如"[用户上传了一张包含数学题目的图片，300KB]"）传入规划层 messages。规划层据此决定是否在 tool_calls 中包含 `process_question`。图片 base64 只在工具执行时使用，不传给规划层 LLM。
  - **图片+文字组合**：用户上传图片同时附带文字时（如"帮我看看这道题的第三问"），编排层将图片摘要与文字拼接为完整用户消息：`"[用户上传了一张包含数学题目的图片，300KB] 帮我看看这道题的第三问该怎么做"`，规划层据此决策
- **执行层**（缓冲后流式，1 次 LLM 调用）：
  - 输入：规划层输出的 strategy + 工具执行结果 + 对话历史 + 题目上下文
  - Prompt（苏格拉底导师）：根据 strategy 执行对应教学策略，一个 Prompt 覆盖所有策略
  - 输出先完整缓冲（供反思层检查），再流式发送给学生
  - Prompt 内嵌 `python:figure` 代码块输出规范，沿用当前 Node C 的绘图约定
- **`python:figure` 处理**：执行层输出缓冲完成后，解析完整文本中的 `python:figure` 代码块，调用 `render_figure` 工具，将图片 URL 作为 `figure_result` SSE 事件发送
- 验证：完整对话流程可用（引导 → 追问 → 直接解答 → 总结）
- **交付物**：规划层 + 执行层 Prompt 和逻辑 + `figure_result` SSE 事件 + 集成测试
- **工作量**：2 天

### Story R.4: 实现反思层和 Agent 编排
- **反思层**（两级检查：正则必过，LLM 按需触发）：
  - 一级检查（正则，每轮必过，零 LLM 开销）：
    - 引导/拆解模式（`socratic_guide` / `step_breakdown`）：
      - 正则匹配最终答案泄露模式（如 "答案是 X"、"所以 X=5"）
      - 检测到泄露 → 从输出文本中删除答案部分，替换为引导性提示
    - 直接解答模式（`direct_answer`）：
      - 确认输出中包含"最终答案"标注，缺失则追加提示
    - 总结/出题模式（`summarize_and_similar`）：
      - 确认总结要点不少于 2 条
      - 确认相似题不包含答案
  - 二级检查（LLM，按需触发，使用 `llm_model_reflexion`）：
    - 触发条件（满足任一即触发）：
      - `extract_knowledge` 返回 `difficulty == "困难"`（数据已有，零成本判断）
      - 规划层从用户消息中识别不满信号（如"不对"、"还是错"、"这不是我要的"），在规划层输出中设置 `need_deep_reflexion: true`
    - 非流式调用 LLM，Prompt："检查以下解答是否存在计算错误或逻辑跳跃"，输入执行层完整输出
    - 检测到错误 → 修正后输出
    - 未检测到错误 → 原样输出（多一次调用但无内容改动）
- **Agent 编排**（`agent/service.py`，Plan-and-Solve 调度）：
  ```
  stream_chat(request) → AsyncIterator[SSE_Event]:
    1. 加载对话历史（从 ChatMessage 表，最近 20 条）
    2. 构建规划层输入：历史消息 + 用户最新消息（图片预处理为摘要）
    3. 调用规划层（非流式）→ 获取 {strategy, tool_calls, ...}
    4. 按 tool_calls 顺序执行工具，收集结果，更新会话状态
       - 若 question_type != "continue_dialogue" → 清空 current_question/current_knowledge/current_diagram（避免换题时旧上下文污染）
       - process_question → 更新 current_question/current_diagram（context_ready 由 current_question IS NOT NULL 推导）
       - extract_knowledge → 更新 current_knowledge
    5. 调用执行层（缓冲完整输出）
    6. 调用反思层 → 检查/修正缓冲区内容
    7. yield message_start
    8. 将修正后的内容流式 yield delta（逐段发送）
    9. 解析 python:figure → 调用 render_figure → yield figure_result
    10. yield message_end
  ```
  **Plan-and-Solve 的核心**：规划层一次性输出完整计划（含 tool_calls 列表），编排层按计划顺序执行工具，不需要 LLM 循环中反复决策。工具调用顺序由规划层决定，编排层只负责执行。
- **会话状态管理**：`current_question`/`current_diagram`/`current_knowledge` 保留在 `ChatSession` 表中，由编排层在步骤 4 后更新；`context_ready` 由 `current_question IS NOT NULL` 推导，不单独建列
- **Memory**：从 `ChatMessage` 表加载最近 20 条历史，构造 OpenAI 格式消息列表 `[{role, content}]` 传入 LLM
- **错误处理**：编排循环中每一步都可能失败，统一处理：
  - process_question 失败 → yield error("题目识别失败，请重新上传")
  - 规划层/执行层 LLM 调用失败 → yield error("AI 服务暂时不可用")
  - render_figure 超时/失败 → 不阻塞主流程，跳过图片，在 delta 中保留代码块文本
- **Token 用量追踪**：每次 LLM 调用后，从响应中提取 `usage` 字段，按层汇总记录到 `ChatMessage.raw_metadata` 中，格式如：
  ```json
  {"usage": {"planning": {"prompt_tokens": 150, "completion_tokens": 50}, "tools": {"process_question": {"prompt_tokens": 200, "completion_tokens": 100}}, "solving": {"prompt_tokens": 500, "completion_tokens": 300}, "reflexion": {"prompt_tokens": 100, "completion_tokens": 80}}}
  ```
- 验证：反思层能拦截泄露答案的输出；Agent 编排完整闭环
- **交付物**：反思层 + Agent 编排服务 + 集成测试
- **工作量**：1.5 天

### Story R.5: 重写 ChatService 和文件上传
- DifyChatService → AgentChatService，使用 R.4 的 Agent 编排服务
- **ChatCompletionRequest 新 Schema**（重构后）：
  ```python
  class ChatCompletionRequest(BaseModel):
      session_id: str | None = None
      message: str = Field(min_length=1)
      asset_ids: list[str] = Field(default_factory=list)
      client_user_id: str = "anonymous"
      current_question: str | None = None
      current_diagram: str | None = None
      current_knowledge: dict | None = None
  ```
  变更：删除 `mode`（规划层自主决定 strategy）、删除 `file_ids`（统一用 `asset_ids`）。`current_question`/`current_diagram`/`current_knowledge` 保留，编排层可据此判断是否已有上下文（减少重复工具调用），但规划层有权忽略这些字段重新识别。**注意：删除 `mode` 和 `file_ids` 是 API breaking change，Sprint 3 前端需同步移除这两个字段的发送逻辑**
- 图片上传重写：
  - `ImageUploadService` 不再依赖 `DifyUploadClient`
  - 上传流程：接收图片 → 校验/压缩 → 保存到存储 → 记录 asset
  - 存储方案复用现有抽象：开发阶段 `LocalAssetStorage`（本地磁盘），生产阶段 `MinioAssetStorage`（与当前 assets 存储一致），通过配置切换
  - 聊天时使用 `asset_id` 查询存储获取图片，读取为 base64 传给 `process_question` 工具
  - 图片 base64 体积控制：前端压缩 + 后端压缩，预计单张 < 500KB
- SSE 事件格式不变（message_start/delta/message_end/error），新增 `figure_result` 事件
- 验证：后端 API 接口行为不变，mock 测试通过
- **交付物**：AgentChatService + 更新后的文件上传逻辑
- **工作量**：1 天

### Story R.6: 清理 Dify 依赖
- 删除 `backend/app/services/dify.py`
- 删除 `backend/tests/test_dify_client.py`
- 重写 `backend/tests/test_chat_service.py`、`test_files_service.py`、`test_regression_chatflow_modes.py`
- 从 `config.py` 删除 `dify_api_url`/`dify_api_key`，新增 LLM 配置项（`llm_api_url`/`llm_api_key` + 6 组模型配置：`llm_model_{planning,question_parse,solving,reflexion,vision,knowledge}` 及各自可选的 `_url`/`_key` 覆盖）
- 从 `deps.py` 删除 DifyClient 构造，替换为 LLM Client
- 从 `docker/.env` 删除 `DIFY_*` 配置，新增 `LLM_*` 配置
- 从 `scripts/setup.sh` 删除步骤 3（部署 Dify）和步骤 6（验证 Dify API），更新步骤编号
- 从 `docker/docker-compose.yml` 删除 Dify 互联注释和 `DIFY_API_URL` 环境变量
- 新增 Alembic 迁移：删除 `dify_conversation_id`、`dify_message_id`、`dify_file_id` 三列，清理对应索引
- 清理模型层：从 `chat_session.py`、`chat_message.py`、`asset.py` 删除 dify 字段定义；`user_tag_history.py` 的 `source` 默认值从 `"dify"` 改为 `"agent"`
- 清理 Schema 层：从 `files.py` 删除 `dify_file_id`；从 `chat.py` 删除 `mode` 和 `file_ids` 字段（重构后由规划层自主决定 strategy，前端不需传入；文件统一用 `asset_ids`）
- 清理编排层：`sessions.py` 的 `update_context` 移除 `mode` 参数和 `mode != "new_question"` 守卫，编排层直接按需更新上下文字段
- 验证：`grep -rn "dify\|Dify\|DIFY" backend/` 无结果；全量测试通过
- **交付物**：清理后的代码 + 通过的测试
- **工作量**：1 天

### Story R.7: 清理 Dify Docker 和更新部署方案
- 停止并删除 Dify Docker 容器：`docker compose --project-name dify down`
- 删除 Dify Docker 镜像：`dify-api:1.14.0`、`dify-web:1.14.0`、`dify-sandbox:0.2.15`、`dify-plugin-daemon:0.6.0`
- 删除 Dify 源码目录：`rm -rf dify/`
- 删除 Dify Docker volumes（确认无业务数据后）：`dify-db_postgres`、`dify-redis`、`dify-weaviate` 等
- 从 `.gitignore` 删除 `dify/` 排除规则
- 更新 `docker/docker-compose.yml`：
  - 移除 `studyhelper_net` 的 `external: true`（不再需要与 Dify 共享网络）
  - 移除 backend 服务的 `DIFY_API_URL` 环境变量
  - 新增 LLM 环境变量：`LLM_API_URL`/`LLM_API_KEY` + 6 组模型配置（`LLM_MODEL_{PLANNING,QUESTION_PARSE,SOLVING,REFLEXION,VISION,KNOWLEDGE}` 及各自可选的 `_URL`/`_KEY` 覆盖）
- 更新 `docker/.env`：删除 Dify 相关端口避让注释，新增 LLM 配置说明
- 更新 `scripts/setup.sh`：移除 Dify 部署步骤，简化为纯业务服务部署
- 验证：`docker compose up -d` 可正常启动所有业务服务；无 Dify 容器运行
- **交付物**：清理后的 Docker 配置 + 部署脚本
- **工作量**：0.5 天

### Story R.8: 更新文档
- 更新 `docs/framework.md`：
  - AI 编排层从 Dify 改为 FastAPI Agent
  - 架构图移除 Dify 双 compose 设计
  - 新增 Agent 分层架构描述（输入层/规划层/执行层/反思层）
  - 技术决策记录新增"从 Dify 迁移到自建 Agent"及理由
- 更新 `tasks/product_backlog.md`：新增 Epic"Agent 架构重构"，标注完成状态
- 更新 `tasks/planning.md`：Sprint Refactor 标记为已闭环，Sprint 3 状态调整
- 更新 `docs/prompts/` 目录：原 Prompt 文件标注为"已迁移至代码"，保留作参考
- 验证：所有文档与代码实际状态一致
- **交付物**：更新后的文档
- **工作量**：0.5 天

## 时间估算

| Story | 工作量 |
|-------|--------|
| R.1 LLM 客户端 | 1 天 |
| R.2 Agent 工具 | 1 天 |
| R.3 规划层 + 执行层 | 2 天 |
| R.4 反思层 + Agent 编排 | 1.5 天 |
| R.5 ChatService 重写 | 1 天 |
| R.6 清理 Dify 代码依赖 | 1 天 |
| R.7 清理 Dify Docker + 部署方案 | 0.5 天 |
| R.8 更新文档 | 0.5 天 |
| **合计** | **8.5 天** |

## 验证方式

1. 后端全量 mock 测试通过（37 passed 基线不降），具体覆盖：
   - LLM 调用全部 mock（用固定 JSON 响应），不依赖外部 API
   - Agent 编排覆盖 5 个 question_type × 核心策略组合（至少：logical_calculation+socratic_guide, direct_answer_request+direct_answer, continue_dialogue+step_breakdown, continue_dialogue+summarize_and_similar, homework_help+knowledge_lookup）
   - 反思层正则每种模式至少 1 个测试用例（答案泄露拦截、最终答案标注检测、要点数量检测、相似题答案检测）
   - 规划层 JSON 解析容错至少 1 个测试用例（非法 JSON → fallback 默认策略）
2. 使用真实几何题图，跑完整答疑闭环：上传图片 → 引导解答 → 继续追问 → 直接解答 → 总结+相似题
3. 反思层能拦截泄露答案的引导输出
4. python:figure 代码块自动执行并返回图片
5. SSE 流式输出事件类型与重构前一致（message_start/delta/message_end/error），data 格式按新契约输出，新增 `figure_result` 事件正常触发
6. `grep -rn "dify\|Dify\|DIFY" backend/` 无新增结果
7. `docker compose up -d` 可正常启动所有业务服务，无 Dify 依赖

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 规划层 JSON 输出不稳定：LLM 不总输出合法 JSON，导致解析失败 | 高 | 高 | R.3 中实现 JSON 容错：提取 ```json``` 代码块→补全括号→修复失败则 fallback 为默认策略 `{continue_dialogue, socratic_guide, [], false}` |
| 多轮上下文漂移：去掉 Dify 的 context_ready 护卫后，Agent 可能误判题目边界（学生换题但 current_question 未清空） | 中 | 高 | 编排层在规划层输出 `question_type != "continue_dialogue"` 时（即新提问类型：logical_calculation/definition/homework_help/direct_answer_request），无论是否调用工具，都立即清空 `current_question`/`current_knowledge`/`current_diagram`，避免旧上下文污染 |
| 反思层正则漏报：隐性答案泄露（如"这个角等于 60°"）无法拦截 | 中 | 低 | 设计决策 #3 已承认此取舍：误杀比漏报更严重，扩展正则会误杀直接解答模式下的正确输出。漏报的代价可接受 |
| LLM API 网络抖动：编排层一次请求 3-4 次 LLM 调用，任一失败整流断裂 | 中 | 高 | R.1 LLM 客户端内置指数退避重试（最多 2 次，仅 5xx/超时） |
| 执行层 Prompt 合并难度：将 Node C（苏格拉底引导）和 Node D（直接解答）合并为一个多策略 Prompt，输出风格可能不一致 | 中 | 中 | R.3 交付时用 3-5 道测试题验证每种 strategy 的输出风格，Prompt 迭代至风格稳定 |

## 依赖关系

```
R.1 (LLM 客户端) ──→ R.2 (Agent 工具) ──→ R.3 (规划层+执行层) ──→ R.4 (反思层+编排)
                                                                         │
                                                                         ▼
                                                                   R.5 (ChatService 重写)
                                                                         │
                                                                    ┌────┴────┐
                                                                    ▼         ▼
                                                              R.6 (代码清理) R.7 (Docker 清理)
                                                                    │         │
                                                                    └────┬────┘
                                                                         ▼
                                                                   R.8 (文档更新)
```

关键依赖说明：
1. R.1 是基础，所有后续 Story 依赖 LLM 客户端
2. R.2-R.4 是 Agent 核心能力，必须按顺序实施
3. R.5 依赖 R.4 的 Agent 编排完成
4. R.6/R.7 可与 R.5 部分并行（先清理明显不用的，再等 R.5 完成后最终验证）
5. R.8 最后执行，确保文档与代码一致

## 建议执行顺序

1. **R.1** — LLM 客户端，基础依赖
2. **R.2** — Agent 工具定义
3. **R.3** — 规划层 + 执行层
4. **R.4** — 反思层 + Agent 编排
5. **R.5** — ChatService 重写
6. **R.6** — 清理 Dify 代码依赖（可与 R.5 后半段并行）
7. **R.7** — 清理 Dify Docker + 部署方案
8. **R.8** — 更新文档
9. **全量端到端验收**
