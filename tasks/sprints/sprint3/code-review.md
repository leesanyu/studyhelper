# Sprint 3 代码检视报告

## 背景

Sprint 3 完成了 Uni-app 前端搭建和后端 Agent 架构（Plan-and-Solve + Reflexion）的对接。本次检视对照 `tasks/sprints/sprint3/planning.md` 和 `tasks/sprints/sprint-refactor/planning.md` 的设计，检查：设计实现完整性、硬编码配置、逻辑流程合理性，以及"前端发送消息后收不到数据"的根因。

---

## 一、设计实现完整性问题（5 项）

### 1.1 `SqlAlchemyChatMessageRepository` 缺少 `get_messages` 方法 [严重]

**位置**: `backend/app/services/messages.py` — `SqlAlchemyChatMessageRepository` 类

**问题**: `AgentService` 的 `MessageRepository` 协议要求实现 `get_messages(session_id, limit)` 方法，但 `SqlAlchemyChatMessageRepository` 只实现了 `create_message`，**完全没有 `get_messages`**。

**影响**:
- `_load_chat_history()` 调用 `self._message_repo.get_messages()` 时抛出 `AttributeError`
- 被 try/except 静默吞掉，返回 None → **对话历史永远不加载**
- LLM 没有历史上下文，多轮对话能力完全丧失
- 这是核心功能缺陷

### 1.2 `SandboxService` 接口签名不匹配 [严重]

**位置**:
- 协议定义: `backend/app/agent/service.py` — `SandboxService` Protocol
- 实际实现: `backend/app/services/sandbox.py` — `DockerPythonFigureSandboxService`

**问题**:
- 协议定义: `render_figure(self, code: str, width=800, height=800) -> dict`
- 实际实现: `render_figure(self, request: PythonFigureRequest) -> dict`
- 调用方式: `await self._sandbox_service.render_figure(figure_code)` — 传了 `str`，但实际方法需要 `PythonFigureRequest` 对象

**影响**:
- 运行时 TypeError，被 try/except 捕获 → **figure_result 事件永远不会发送**
- 几何图形渲染功能完全失效
- 前端 FigureBlock 永远停留在 `waiting` 状态，5 秒后标记为 `failed`

### 1.3 `_persist_messages` 传参类型不匹配 [中等]

**位置**: `backend/app/agent/service.py` — `_persist_messages` 方法

**问题**:
- 传入 `dict`：`self._message_repo.create_message({"session_id": ..., "role": "user", ...})`
- `SqlAlchemyChatMessageRepository.create_message` 期望 `ChatMessageCreate` dataclass
- 运行时 TypeError，被 try/except 吞掉 → **消息永远不持久化**
- `message_end` 事件中的 `message_id` 永远为空字符串

### 1.4 `current_knowledge` 存储为 JSON 字符串而非 dict [轻微]

**位置**: `backend/app/agent/service.py` — `_update_session_question` 和 `_update_session_knowledge`

**问题**:
```python
current_knowledge=_json.dumps({...}, ensure_ascii=False)
```
- `ChatSession.current_knowledge` 列类型是 `JSON`
- `json.dumps()` 生成字符串，存入 JSON 列会被二次编码
- 读取时 `current_knowledge` 是字符串而非 dict，但 `build_planning_messages` 中两种类型都做了 `str()` 转换，所以不影响功能

### 1.5 前端请求的上下文字段被忽略 [轻微]

**位置**: `backend/app/services/chat.py` — `AgentChatService.stream_chat`

**问题**:
- `ChatCompletionRequest` 有 `current_question/current_diagram/current_knowledge` 三个可选字段
- `AgentChatService.stream_chat` 只传递了 `session_id/message/asset_ids/client_user_id`
- 这三个字段完全被忽略
- 设计意图是"会话状态由编排层管"（从数据库加载），所以这些字段是冗余的，但 Schema 中保留它们容易造成误解

---

## 二、硬编码配置项问题（2 项）

### 2.1 模型名 `qwen3.6-plus` 可能不存在 [严重]

**位置**: `backend/app/core/config.py` — 6 个模型场景的默认值

**问题**:
- 默认值: `llm_model_planning = "qwen3.6-plus"` 等共 5 个场景
- `llm_model_vision = "qwen-vl-max"` （这个是有效的）
- `qwen3.6-plus` 不是 DashScope 标准模型名，可能应为 `qwen-plus` 或 `qwen3-plus`
- 如果模型名不存在，所有 LLM 调用都会失败
- **需要确认当前 `.env` 中是否覆盖了这些默认值**

### 2.2 `llm_api_key` 默认值为占位符 [轻微]

**位置**: `backend/app/core/config.py`

**问题**:
- 默认值: `llm_api_key: str = Field(default="your-llm-api-key", repr=False)`
- 当前 `.env` 中已配置真实 key，但如果 `.env` 缺失或 key 名不匹配，会用占位符调用 API
- 建议改为必填项或启动时校验

---

## 三、逻辑流程问题（4 项）

### 3.1 反思层调用未包裹 try/except [严重 — 可能是前端收不到数据的原因之一]

**位置**: `backend/app/agent/service.py` — `stream_chat` 方法

**问题**:
```python
# 8. 调用反思层
reflexion_result = await reflexion_check(
    self._llm_client,
    content=solve_result.content,
    strategy=plan_result.strategy,
    difficulty=difficulty,
    need_deep_reflexion=plan_result.need_deep_reflexion,
)
```
- 这段代码没有 try/except
- 当 `difficulty == "困难"` 或 `need_deep_reflexion == True` 时，`deep_reflexion` 会调用 LLM
- 如果 LLM 调用失败，异常直接传播到 async generator 外部
- `StreamingResponse` 已经发送了响应头，无法再返回 HTTP 错误
- **后果: 连接直接断开，前端收不到 error 事件，也收不到任何数据**

### 3.2 整个 Agent 流水线阻塞后才发送第一个 SSE 事件 [中等 — 影响用户体验]

**位置**: `backend/app/agent/service.py` — `stream_chat` 方法

**问题**:
- "先缓冲再流式"设计导致完整流水线（Plan → Tool → Solve → Reflexion）全部执行完毕后，才 yield 第一个 `message_start` 事件
- 4 次串行 LLM 调用，总计可能 30+ 秒
- 期间前端只看到 loading 动画，无任何反馈
- 用户容易误判为"卡死了"或"没有数据"

**建议**: 先 yield `message_start`（Plan 阶段前），让前端知道连接已建立；至少在 tool 执行后 yield 一个进度提示

### 3.3 `_format_tool_results` 的 `tokens` 返回值永远为空 [轻微]

**位置**: `backend/app/agent/service.py` — `_format_tool_results`

**问题**:
```python
tokens: dict[str, dict[str, int]] = {}  # 初始化为空 dict
# ... 但从未向 tokens 中写入任何值
return tokens, texts
```
- `tool_tokens` 在 `_persist_messages` 中被写入 `usage_summary["tools"]`，但永远是空 dict
- tool 调用的 token 用量丢失

### 3.4 换题时先清空上下文再执行工具，失败时上下文丢失 [轻微]

**位置**: `backend/app/agent/service.py` — `stream_chat` 方法

**问题**:
```python
# 5. 换题时清空旧上下文
if plan_result.question_type != "continue_dialogue":
    await self._clear_session_context(session_id)

# 6. 执行工具（按 plan_result.tool_calls 顺序）
for tool_name in plan_result.tool_calls:
    ...
```
- 先清空，后写入。如果工具执行中途失败，旧上下文已清空但新上下文未写入
- 建议改为：工具成功后才清空旧上下文并写入新上下文（原子替换）

---

## 四、前端收不到数据的根因分析 [核心问题]

经过完整的代码流追踪，前端收不到数据的最可能原因是**多个问题叠加**：

### 根因 1 [最高概率]: Agent 流水线异常导致 async generator 崩溃

**完整链路追踪**:
1. 前端 POST → 后端 `chat_completions` → `StreamingResponse(stream())`
2. `stream()` 调用 `chat_service.stream_chat(request)`
3. `AgentService.stream_chat()` 开始执行 Agent 流水线
4. 如果任意 LLM 调用抛出未捕获异常 → async generator 崩溃
5. `StreamingResponse` 已发送 200 响应头，无法改为错误响应
6. 连接直接断开，前端 `ReadableStream` 读到 EOF

**最可能的触发点**:
- `reflexion_check` 未包裹 try/except（3.1）
- 模型名 `qwen3.6-plus` 如果不存在，`plan()` 内的 `chat_json()` 抛出 `openai.BadRequestError`
- 这个异常会被 `plan()` 外的 try/except 捕获并 yield error 事件 ✓
- 但如果异常类型不是 `Exception` 的子类（极罕见），或异常发生在 yield 之后，则无法捕获

### 根因 2 [高概率]: Vite devServer 代理 SSE 响应被缓冲

**关键发现**:
- `frontend/vite.config.ts` 没有 proxy 配置
- `manifest.json` 配置了 `devServer.proxy`：`"/api" → "http://localhost:8000"`
- Uni-app 的 `@dcloudio/vite-plugin-uni` 插件会将此配置注入 Vite 的 devServer
- 但此代理配置**没有 SSE 专用设置**（如禁用压缩、设置超时等）
- Vite 底层的 `http-proxy` 可能缓冲 SSE 响应体

**验证方法**: 绕过代理，直接访问 `http://localhost:8000/api/v1/chat/completions`，看能否收到流式数据

### 根因 3 [高概率]: 整个流水线耗时过长，前端误判为无数据

- 4 次串行 LLM 调用（plan → process_question → extract_knowledge → solve）
- 每次调用 2-8 秒，总计可能 30+ 秒
- 这期间前端只看到 loading 动画，没有任何数据到达
- 用户可能在这期间放弃或认为出了问题

### 根因 4 [中概率]: `process_question` 工具中 `image_base64=None, text=message` 的组合可能异常

**位置**: `backend/app/agent/service.py` — 工具执行循环

**问题**:
```python
result = await process_question(
    self._llm_client,
    image_base64=image_base64,  # 可能为 None
    text=message,               # 用户消息
)
```
- 当没有图片时，`image_base64=None`, `text=message`
- `process_question` 内部: `scene = "vision" if image_base64 else "question_parse"`
- `scene="question_parse"` → 使用 `llm_model_question_parse`（默认 `qwen3.6-plus`）
- 如果模型名无效，API 返回错误 → 被 try/except 捕获 → yield error 事件
- 但这个 error 事件应该能到达前端...

**除非**: `llm_client.chat_json()` 中的 `response_format={"type": "json_object"}` 不被该模型支持，导致 API 返回 400 错误，且错误格式特殊导致 openai SDK 抛出非标准异常

---

## 五、问题优先级汇总

| # | 问题 | 严重度 | 是否阻塞前端收数据 |
|---|------|--------|-------------------|
| 1.1 | `get_messages` 方法缺失 | 严重 | 间接（无历史上下文） |
| 1.2 | `render_figure` 接口不匹配 | 严重 | 否（figure 渲染失效，不影响主文本） |
| 1.3 | 消息持久化类型不匹配 | 中等 | 否（message_id 为空） |
| 1.4 | `current_knowledge` JSON 二次编码 | 轻微 | 否 |
| 1.5 | 前端上下文字段被忽略 | 轻微 | 否 |
| 2.1 | 模型名 `qwen3.6-plus` 可能不存在 | **严重** | **是 — 所有 LLM 调用失败** |
| 2.2 | `llm_api_key` 默认占位符 | 轻微 | 否 |
| 3.1 | 反思层未包裹 try/except | **严重** | **是 — 可能导致连接断开** |
| 3.2 | 流水线阻塞 30+ 秒 | 中等 | **是 — 体验差，误判为无数据** |
| 3.3 | tool token 用量丢失 | 轻微 | 否 |
| 3.4 | 换题时上下文非原子替换 | 轻微 | 否 |

---

## 六、建议排查顺序

1. **检查后端日志**: 确认 `plan()` 调用是否成功，LLM API 是否返回了错误
2. **确认模型名**: 验证 `qwen3.6-plus` 在 DashScope 中是否存在；在 `.env` 中显式覆盖模型名
3. **绕过 Vite 代理测试**: 用 curl 或浏览器直接访问 `http://localhost:8000/api/v1/chat/completions`，确认后端 SSE 能正常输出
4. **为 reflexion_check 添加 try/except**: 防止未捕获异常导致连接断开
5. **先 yield message_start**: 在 Plan 调用之前就发送 message_start 事件，让前端知道连接已建立
6. **修复接口不匹配**: `render_figure` 签名对齐、添加 `get_messages` 方法、修正 `_persist_messages` 传参

---

## 讨论区

### 根因定位完成（2026-05-21）

#### 确认的根因：「先缓冲再流式」设计 + LLM 调用总耗时过长 = 前端长时间无数据

**实测数据**（几何题 `tests/questions/几何-线段-全等.jpg`）：

| 步骤 | 耗时 | 说明 |
|------|------|------|
| Plan | ~10s | 规划层 LLM 调用 |
| process_question (vision) | ~10s | 视觉模型处理图片 |
| extract_knowledge | ~33s | 知识点提取（chat_json 较慢） |
| Solve (streaming) | **83s** | 执行层流式生成完整回复 |
| Reflexion (困难题) | ~30s | 二级 LLM 自检 |
| **总计** | **~166s** | **2分46秒** |

**关键问题**：当前代码在所有步骤完成（含反思）后，才 yield 第一个 `message_start` 事件。前端在这 2-3 分钟内只看到 loading 动画，无任何数据反馈。

**验证过程**：
1. ✅ curl 直测后端（纯文字 "你好"，不触发工具调用）→ SSE 正常，秒级响应
2. ✅ curl 直测后端（"1+1等于几"，触发工具但 LLM 回复短）→ SSE 正常，~30s
3. ❌ curl 直测后端（几何题图片，触发完整流水线）→ 需 180s 超时才能收到数据
4. ✅ Python 直接调用 `stream_chat()` → 各步骤均正常，只是慢
5. ✅ Vite 代理修复后 curl 通过 5173 端口 → SSE 正常

**结论**：Vite 代理缓冲是次要问题（已修复），**核心问题是流水线总耗时过长 + 先缓冲再流式**。

#### 修复方案

**必须修复**（解决前端长时间无数据）：

1. **提前 yield `message_start`**：在 Plan 调用之前就发送 `message_start`，让前端知道连接已建立
2. **增加进度事件**：在工具执行、Solve 阶段 yield `thinking` 类事件，前端展示"正在分析题目…"等提示
3. **为 reflexion_check 添加 try/except**：防止未捕获异常导致 async generator 崩溃

**应该修复**（Sprint 3 检视中的其他问题）：

4. **`render_figure` 签名不匹配**：`SandboxService` Protocol 与 `DockerPythonFigureSandboxService` 实现不一致
5. **`get_messages` 方法缺失**：`SqlAlchemyChatMessageRepository` 缺少此方法，对话历史不加载
6. **`_persist_messages` 传参类型不匹配**：传 dict 而非 `ChatMessageCreate`，消息不持久化
7. **`_format_tool_results` 的 tokens 丢失**：tool 调用的 token 用量永远为空

**优化建议**（降低延迟）：

8. **extract_knowledge 使用 `chat()` 替代 `chat_json()`**：`chat_json()` 因 `response_format={"type":"json_object"}` 要求 prompt 中含 "json" 且可能增加推理时间
9. **Solve 改为实时流式**：当前先完整缓冲再逐段发送，可改为边生成边发送（反思层改为后置异步检查）
10. **验证模型名**：`qwen3.6-plus` 当前可工作，但需确认是否为官方标准名称

