# 实施计划：Agent SSE 实时流式改造 + Sprint3 检视问题修复

## Context

Sprint 3 代码检视发现前端"发送消息后收不到数据"，经排查根因是：

1. **"先缓冲再流式"设计**：Solve 层完整缓冲输出（几何题实测 83s），反思层再检查（30s），全部完成后才 yield 第一个 SSE 事件。几何题全流程 166s，前端 2-3 分钟零反馈。
2. **Vite 代理 SSE 缓冲**：已修复（代理配置迁移至 vite.config.ts），但仍是次要问题。

用户要求：每个步骤的结果实时返回前端，Solve 层实时流式而非全缓冲。同时修复检视中发现的其他问题。

---

## 一、关键问题分析

### 1.1 Python 生图（figure）是否受影响

**当前流程**：
```
Solve 完整缓冲 → 解析 python:figure 代码块 → render_figure → yield figure_result
```

**改造后流程**：
```
Solve 实时流式 yield delta → delta 中包含 python:figure 代码块的文本
→ 全部 delta 发完后 → 解析完整内容中的 python:figure 代码块
→ render_figure → yield figure_result
```

**影响分析**：

- `python:figure` 代码块在 LLM 流式输出中是逐字到达的，需要等完整代码块闭合后才能解析和执行
- 实时流式后，代码块文本会先作为 delta 发送给前端（前端用 MarkdownRenderer 渲染为代码块或 FigureBlock waiting 状态）
- **render_figure 的执行时机不变**：仍然在 Solve 完成后解析完整内容、提取代码块、执行沙箱
- **figure_result 事件时机不变**：仍在所有 delta 之后、message_end 之前发送
- **结论：不受影响**。只是用户先看到代码文本，后看到替换后的图片，这反而比之前等 3 分钟什么都没有好得多

**唯一需要注意**：Solve 层不再返回 `SolveResult`（含解析好的 `figure_blocks`），需要在流式结束后单独解析一次完整内容来提取 `python:figure` 代码块。

### 1.2 前端超时实践

**当前前端代码**（`frontend/src/utils/sse.ts`）：

```typescript
fetch(BASE_URL + '/api/v1/chat/completions', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
  signal: controller.signal,  // AbortController，手动中断
})
```

- **没有设置 fetch 超时**：`fetch` 本身没有 `timeout` 参数，超时完全依赖 `AbortController` 的手动调用
- **浏览器默认行为**：Chrome/Firefox 对 SSE/长连接无硬性超时限制，只要连接存活就会持续读取
- **Nginx 代理超时**：生产环境 `proxy_read_timeout 300s`（5 分钟），足够覆盖

**改造后影响**：
- `message_start` 在 <1s 到达 → fetch 请求立即收到响应 → 浏览器不会因"无响应"超时
- delta 持续到达 → 连接保持活跃 → 不会触发任何超时
- **结论：前端无需调整超时**。改造后体验大幅改善，超时不再是问题

---

## 二、SSE 事件类型扩展

### 新增事件类型

| 事件 | data 格式 | 时机 | 前端用途 |
|------|-----------|------|----------|
| `thinking` | `{"type": "planning"/"tool_exec"/"solving"/"reflexion", "message": "分析题目中..."}` | 各步骤开始时 | 显示进度提示 |
| `tool_result` | `{"tool": "process_question"/"extract_knowledge", "data": {...}}` | 工具执行完成后 | 展示题目识别、知识点标签 |
| `reflexion_patch` | `{"original": "原文片段", "corrected": "修正后片段"}` | 反思层修改内容时 | 提示"已修正一处计算错误" |

### 改造后完整事件序列

```
message_start → thinking(planning) → [thinking(tool_exec) → tool_result]* → thinking(solving) → delta×N(实时) → [figure_result]* → [reflexion_patch?] → message_end
```

几何题实测时序：
```
0s     message_start          ← 立即返回
0s     thinking(planning)     ← 立即返回
10s    thinking(tool_exec)    ← Plan 完成
10s    thinking(识别题目中...)
20s    tool_result(process_question) ← 题目识别完成
20s    thinking(提取知识点...)
53s    tool_result(extract_knowledge) ← 知识点提取完成
53s    thinking(生成回复...)   ← Solve 开始
53s    delta(第一段文字)       ← Solve 开始流式输出！
...    delta×N               ← 持续打字机效果
136s   figure_result          ← render_figure 完成
136s   message_end            ← 完成
```

**对比**：
- 改造前：0-166s 无数据，166s 后一次性收到全部
- 改造后：0s 有反馈，53s 开始出字，体验质变

---

## 三、实施任务分解

### Task 1: 后端 — `stream_chat()` 实时流式改造

**文件**: `backend/app/agent/service.py`

**核心改动**：重写 `stream_chat()` 的事件发送时序

```
1. yield message_start（立即，Plan 之前）
2. yield thinking(planning)
3. 调用 plan() → 获取 plan_result
4. 对每个 tool_call：
   a. yield thinking(tool_exec, message=描述)
   b. 执行工具
   c. yield tool_result(工具名, 结果摘要)
5. yield thinking(solving)
6. 调用 solve()，但改为实时流式：
   a. 不再缓冲完整 SolveResult
   b. llm_client.stream_chat() 的每个 TextDelta 直接 yield 为 delta 事件
   c. 收集完整内容用于后续 figure 解析和反思
7. 解析 python:figure → render_figure → yield figure_result
8. 对收集的完整内容执行 reflexion_check（正则 + 按需 LLM）
9. 如反思修改了内容，yield reflexion_patch
10. 持久化消息
11. yield message_end
```

**关键变更**：`solve()` 函数不再在内部缓冲后返回 `SolveResult`，而是改为接收一个回调，实时将 TextDelta 传出。或者在 `stream_chat()` 中直接调用 `llm_client.stream_chat()` 并手动构建 messages。

**选择方案**：修改 `solve()` 增加 `on_delta` 回调参数，保持分层架构不变：

```python
async def solve(
    llm_client: LLMClient,
    *,
    strategy: str,
    ...,
    on_delta: Callable[[str], None] | None = None,  # 新增：实时 delta 回调
) -> SolveResult:
    # stream_chat 时每个 TextDelta:
    #   1. 调用 on_delta(text) 通知编排层
    #   2. 继续缓冲到 chunks
    # 最终仍返回完整 SolveResult（供 figure 解析和反思使用）
```

### Task 2: 后端 — 反思层改为非阻塞

**文件**: `backend/app/agent/reflexion.py`, `backend/app/agent/service.py`

**改动**：
- 正则检查在 delta 流结束后立即执行（<1ms，不阻塞）
- LLM 自检仅在"困难"题触发，在所有 delta 和 figure_result 之后执行
- 如果修正了内容，yield `reflexion_patch` 事件
- 为 `reflexion_check` 添加 try/except，防止未捕获异常

### Task 3: 后端 — 修复检视中的严重问题

**文件**: `backend/app/agent/service.py`, `backend/app/services/messages.py`, `backend/app/agent/service.py`

3a. **`get_messages` 缺失**：在 `SqlAlchemyChatMessageRepository` 中添加 `get_messages(session_id, limit)` 方法

3b. **`render_figure` 签名不匹配**：对齐 `SandboxService` Protocol 与 `DockerPythonFigureSandboxService` 的签名。方案：修改 `service.py` 中的调用方式，构造 `PythonFigureRequest` 传入

3c. **`_persist_messages` 传参类型不匹配**：将 dict 改为 `ChatMessageCreate` dataclass

3d. **`_format_tool_results` tokens 丢失**：修复 token 用量收集逻辑

3e. **`current_knowledge` JSON 二次编码**：传 dict 而非 `json.dumps()` 字符串给 `update_context`

3f. **换题时上下文非原子替换**：工具成功后再清空旧上下文

### Task 4: 前端 — SSE 事件类型扩展

**文件**: `frontend/src/utils/sse.ts`, `frontend/src/pages/chat/index.vue`

4a. **sse.ts 新增事件类型**：`thinking`、`tool_result`、`reflexion_patch` 的接口定义和分发

4b. **ChatMessage 类型扩展**：新增 `thinking_message` 字段显示当前步骤提示，`tool_results` 字段展示工具结果

4c. **聊天页 UI**：
- `thinking` 事件 → 在 AI 气泡中显示步骤提示（如"正在分析题目..."）
- `tool_result` 事件 → 在 AI 气泡中展示题目识别结果和知识点标签
- `reflexion_patch` 事件 → 可选展示"已修正一处计算错误"提示

### Task 5: 前端 — 清理冗余字段

**文件**: `backend/app/schemas/chat.py`, `frontend/src/utils/sse.ts`

- 从 `ChatCompletionRequest` 移除 `current_question/current_diagram/current_knowledge`（由后端从数据库加载，前端无需传）
- 从 `ChatCompletionPayload` 移除对应字段

---

## 四、验证方案

1. **纯文字测试**：发送"你好"→ 预期 <5s 看到 message_start + thinking + delta
2. **带工具调用测试**：发送"1+1等于几"→ 预期依次看到 thinking→tool_result→thinking→delta
3. **几何题图片端到端**：上传 `tests/questions/几何-线段-全等.jpg` → 预期：
   - <1s: message_start
   - ~10s: tool_result(process_question) 题目识别结果
   - ~53s: tool_result(extract_knowledge) 知识点
   - ~53s: delta 开始流式输出
   - 总时长不变（~166s），但全程有反馈
4. **反思修正测试**：构造一个引导模式泄露答案的回复，确认 reflexion_patch 事件到达前端
5. **异常测试**：LLM 调用失败时确认 error 事件正确返回
6. **对话历史测试**：发送第二条消息，确认历史上下文被正确加载
7. **运行已有测试**：`PYTHONPATH=. python3 -m pytest tests/ -v`

---

## 五、涉及文件清单

| 文件 | 改动类型 |
|------|----------|
| `backend/app/agent/service.py` | 重构 stream_chat() 实时流式 + 修复多个问题 |
| `backend/app/agent/layers.py` | solve() 增加 on_delta 回调 |
| `backend/app/agent/reflexion.py` | 无改动（调用方式不变，仅 service.py 中加 try/except） |
| `backend/app/services/messages.py` | SqlAlchemyChatMessageRepository 添加 get_messages |
| `backend/app/schemas/chat.py` | 移除冗余字段 |
| `frontend/src/utils/sse.ts` | 新增事件类型 |
| `frontend/src/pages/chat/index.vue` | thinking/tool_result UI |
| `frontend/src/api/chat.ts` | ChatMessage 类型扩展 |
