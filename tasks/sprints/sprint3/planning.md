# Sprint 3 Planning：跨端前端搭建与核心答疑闭环

## 1. 目标

搭建 Uni-app (Vue 3) 前端工程，完成聊天页核心 UI、SSE 流式打字机、Markdown/KaTeX 公式渲染、图片上传预览和 python:figure 代码块渲染，实现核心答疑全链路闭环。

> **Sprint Refactor 说明**：后端已从 Dify Chatflow 重构为自建 Agent 架构（Plan-and-Solve + Reflexion）。原 Story 4.1（Dify 分步拆解分支）和 Story 4.2（Dify 总结+相似题分支）已由 Agent 规划层内置，无需前端或后端额外实现。

## 2. 范围

**包含的 Story：**
- Story 3.1: 初始化 Uni-app (Vue 3) 项目，搭建基础 UI 框架
- Story 3.2: 实现聊天对话页
- Story 3.3: 实现流式输出打字机效果（含 figure_result 事件处理）
- Story 3.4: 集成 markdown-it + KaTeX
- Story 3.5: 实现拍照/选图上传
- Story 3.6: 图片预览
- Story 3.7: 实现 AI 回复代码块识别（python:figure 被动接收 figure_result 渲染）
- Story 4.3: 前端实现「不甚理解」/「我会了」悬浮反馈按钮
- Story 4.4: 几何题图形渲染（与 3.7 合并实施）

**不在本 Sprint 范围：**
1. 不实现用户注册/登录，延续匿名用户模式
2. 不实现错题本、薄弱点雷达图和练习模块（Epic 5/6）
3. 不实现微信小程序和 App 适配（Epic 7），Sprint 3 聚焦 H5
4. 不做小程序端的 SSE 兼容适配，该问题记录为技术债务留给 Epic 7
5. 不做性能优化和 CDN 部署

**Sprint 3 启动前必须完成的修补项（Sprint 2 遗留）：**
1. **`/assets` 静态文件服务缺失**：后端返回的 `preview_url`（`/assets/uploads/xxx.png`）和沙箱 `image_url`（`/assets/figures/xxx.png`）均为相对路径，但 Nginx 和 FastAPI 均未提供 `/assets` 路径的服务。**修复方案：在 Nginx 配置中添加 `/assets` location 块，alias 指向后端容器内的 `asset_storage_path` 目录；或在 FastAPI 中挂载 StaticFiles。**
2. **CORS 中间件缺失**：本地开发时前端 Vite dev server 与后端不同源，浏览器会拦截跨域请求。**修复方案：在 FastAPI `create_app` 中添加 `CORSMiddleware`（开发环境允许 `localhost:*`，生产环境由 Nginx 同源代理无需 CORS）。**

## 3. 验收标准

1. Uni-app 项目可本地编译运行 H5，通过 Nginx 代理可正常访问首页、聊天页、历史页 TabBar
2. 聊天页可发送文字消息，AI 回复以 SSE 流式逐字渲染，呈现打字机效果
3. AI 回复中 Markdown 格式正确渲染，行内 `$...$` 和块级 `$$...$$` 公式均由 KaTeX 正确渲染
4. 聊天页可调用摄像头拍照或从相册选图，图片经前端压缩后上传至后端，上传成功后在聊天框展示缩略图
5. 上传图片后可附带文字消息发起答疑，后端返回 `asset_id` 并正确传递给聊天接口
6. AI 回复中的普通代码块展示为代码卡片（含语言标签、复制按钮）
7. AI 回复完成后，后端推送 `figure_result` 事件，前端渲染生成图片，图片可点击预览
8. 聊天页在 AI 回复完成后展示「不甚理解」/「我会了」悬浮按钮，点击后 AI 自动输出对应策略回复：
   - 点击「不甚理解」→ AI 输出更细致的分步引导（Agent 选择 `step_breakdown` 策略）
   - 点击「我会了」→ AI 输出总结要点并生成一道相似题（Agent 选择 `summarize_and_similar` 策略）
9. 会话列表页展示历史会话，点击可进入聊天详情并加载历史消息
10. 全链路验收：使用 `tests/questions/` 中的几何题图，完成「拍照上传 → AI 引导答疑 → 不甚理解 → 分步拆解 → 我会了 → 总结+相似题」完整闭环

## 4. 开工前置条件

1. **Node.js 18+ 已安装**，可执行 `npx` 命令
2. **后端服务可运行**：`docker compose --profile backend up -d` 启动后端、数据库、Redis
3. **LLM API 可用**：`LLM_API_URL` 和 `LLM_API_KEY` 已在 `docker/.env` 中配置
4. **Nginx 已配置前端代理**：`docker/nginx/conf.d/default.conf` 已配置前端静态文件目录 `frontend/dist/build/h5`，`docker-compose.yml` 中 nginx 的 volumes 已挂载该目录
5. **沙箱镜像已构建**：`studyhelper-code-sandbox:latest` 可用
6. **后端接口契约已明确**（本规划第 6 节即为该清单）

## 5. 关键设计决策

1. **SSE 兼容方案：H5 直接使用 fetch + ReadableStream**
   - 微信小程序不支持原生 SSE，但 Sprint 3 聚焦 H5，不需要立即实现小程序兼容
   - 为后续小程序适配预留 `#ifdef H5` / `#ifdef MP-WEIXIN` 条件编译接口层，小程序方案延后到 Epic 7
   - 理由：避免过早引入 polyfill 增加复杂度，H5 方案最稳定、调试最方便

2. **SSE 请求使用 fetch + ReadableStream 而非 EventSource**
   - EventSource 不支持 POST 请求自定义 body，而后端聊天接口是 POST
   - 使用 `fetch` 发起 POST 请求，通过 `response.body.getReader()` 逐块读取 SSE 事件
   - 理由：后端 `POST /api/v1/chat/completions` 要求请求体，EventSource 只能发 GET

3. **Markdown/KaTeX 渲染使用 v-html 而非 webview**
   - H5 端使用 markdown-it 解析为 HTML，KaTeX 渲染公式后输出 HTML，通过 `v-html` 渲染
   - 代码块使用自定义 Vue 组件渲染，以便区分普通代码块和 `python:figure` 代码块
   - 理由：H5 环境下 DOM 操作无障碍，markdown-it + KaTeX 是框架选型时已确定的技术方案

4. **python:figure 代码块前端状态机设计（简化）**
   - 状态：`waiting`（等待 figure_result 事件）→ `success`（渲染图片）/ `failed`（message_end 后未收到 figure_result）
   - 前端在 `message_end` 后检查是否收到对应 `figure_result`；未收到则标记为 `failed`
   - 不再主动调用 `POST /api/v1/sandbox/python-figure`，执行由后端 Agent 完成
   - Story 3.7 和 4.4 合并实施：3.7 负责代码块识别和状态展示，4.4 负责 figure_result 事件接收和图片渲染
   - 理由：后端 Agent 已在 solve 层完成 python:figure 执行，前端只需被动接收结果，状态机大幅简化

5. **@dcloudio/uni-ui 作为 UI 组件库**
   - 使用 `@dcloudio/uni-ui`（DCloud 官方组件库），提供 TabBar、输入框、按钮、图片预览等基础组件
   - 理由：DCloud 官方维护，与 Uni-app 版本同步更新（最近更新 2026-03），peerDependencies 声明完整，兼容性有保障；uv-ui 已于 2023-11 停止维护，不再考虑

6. **图片压缩策略**
   - 前端压缩优先：选图后使用 Canvas 压缩到最大 1600px 长边、JPEG quality 85，再上传
   - 后端兜底压缩：Sprint 2 已实现服务端压缩，前端压缩后体积仍可能超限时由后端二次处理
   - 理由：减少上传带宽和等待时间，后端压缩作为安全兜底

7. **反馈意图通过消息内容传递，由 Agent 规划层自动识别策略**
   - 「不甚理解」发送语义明确的自然语言（如"我还是不太理解，请更细致地引导我"），Agent 规划层识别为 `step_breakdown` 策略
   - 「我会了」发送语义明确的自然语言（如"我理解了，请总结一下并给我一道相似题"），Agent 规划层识别为 `summarize_and_similar` 策略
   - 不使用 `mode` 字段做路由（已从 Schema 中移除），由 Agent 规划层基于消息内容自动分类
   - 理由：Agent 规划层本身就是 LLM 意图分类，反馈消息语义明确，分类准确率接近 100%；无需前端或后端额外路由逻辑

8. **前端项目结构遵循 Uni-app 标准目录规范**
   - `frontend/` 下初始化 Uni-app 项目，源码在 `frontend/src/`
   - 构建产物输出到 `frontend/dist/build/h5/`，与 Nginx 挂载路径一致
   - API 请求封装为 `frontend/src/api/` 统一模块，base URL 从环境变量读取
   - 理由：与 .gitignore 和 docker-compose.yml 中已有路径配置保持一致

9. **Dify 工作流扩展已由 Agent 内置，无需额外实现**
   - `step_breakdown` 和 `summarize_and_similar` 策略已在 Agent 规划层内置
   - 执行层根据策略自动生成对应教学回复，反思层对 `summarize_and_similar` 策略检查相似题不含答案
   - 原 Story 4.1/4.2（Dify 工作流节点）已标记为完成，无需前端或后端额外工作

10. **markdown-it 行内公式 `$...$` 直接在插件配置中开启**
    - 使用 markdown-it-texmath 或 markdown-it-katex 插件时，在插件选项中启用 `$...$` 行内定界符
    - 不使用 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX` 环境变量（该变量是 Next.js 约定，不适用于 Uni-app）
    - 理由：Uni-app 中 markdown-it 配置在 JS 层完成，无需环境变量中转

## 6. 前端接口契约

| 接口 | 方法 | 路径 | 请求 | 响应 | 说明 |
|------|------|------|------|------|------|
| 聊天 SSE | POST | `/api/v1/chat/completions` | `{ session_id?, message, asset_ids?, client_user_id?, current_question?, current_diagram?, current_knowledge? }` | SSE 流：`message_start` / `delta` / `figure_result` / `message_end` / `error` | 不再携带 `mode` 和 `file_ids` 字段；反馈意图通过消息内容传递 |
| 文件上传 | POST | `/api/v1/files/upload` | multipart: `file` + `client_user_id` | `{ asset_id, preview_url, mime_type, size }` | 支持 png/jpeg/webp，最大 20MB；preview_url 为相对路径 |
| 沙箱执行 | POST | `/api/v1/sandbox/python-figure` | `{ code, session_id?, message_id?, width?, height? }` | `{ asset_id, image_url, mime_type, width, height, elapsed_ms, stderr }` | 前端不再主动调用；该接口保留供其他场景使用 |
| 创建会话 | POST | `/api/v1/sessions` | `{ client_user_id?, title?, asset_ids? }` | `{ session_id, title, status, messages[], ... }` | 返回完整会话详情 |
| 会话列表 | GET | `/api/v1/sessions?client_user_id=xxx` | query: `client_user_id` | `{ items: [{ session_id, title, status, last_message, subject, knowledge_points }] }` | 按更新时间倒序 |
| 会话详情 | GET | `/api/v1/sessions/{session_id}` | path: `session_id` | `{ session_id, title, status, client_user_id, asset_ids, messages[] }` | 含消息历史 |
| 健康检查 | GET | `/health` | - | `{ status, ... }` | 验证后端可用性 |

**SSE 事件格式：**

```
# message_start 事件
data: {"event": "message_start", "data": {"session_id": "xxx"}}

# delta 事件（多次）
data: {"event": "delta", "data": {"text": "增量文本片段", "session_id": "xxx"}}

# figure_result 事件（python:figure 代码块执行完成后推送）
data: {"event": "figure_result", "data": {"asset_id": "xxx", "image_url": "/assets/figures/xxx.png"}}

# message_end 事件
data: {"event": "message_end", "data": {"session_id": "xxx", "message_id": "xxx"}}

# error 事件
data: {"event": "error", "data": {"code": "error_code", "message": "错误描述"}}
```

**错误码汇总：**

| 错误码 | HTTP | 场景 |
|--------|------|------|
| `asset_not_found` | 404 | 聊天请求中 asset_id 不存在 |
| `session_not_found` | 404 | 聊天请求中 session_id 不存在 |
| `ai_unavailable` | 502 | LLM API 不可用 |
| `tool_error` | 500 | Agent 工具执行失败 |
| `invalid_file_type` | 400 | 上传文件类型不支持 |
| `file_too_large` | 413 | 上传文件超过 20MB |
| `invalid_image` | 400 | 上传文件不是有效图片 |
| `sandbox_rejected` | 400 | 沙箱代码静态校验不通过 |
| `sandbox_execution_failed` | 400 | 沙箱代码执行出错 |
| `sandbox_timeout` | 408 | 沙箱执行超时 |
| `sandbox_unavailable` | 500 | 沙箱镜像不可用 |

## 7. Story 分解与实施任务

### Story 3.1: 初始化 Uni-app (Vue 3) 项目，搭建基础 UI 框架（首页、聊天页、历史页 TabBar）

- [ ] 使用 CLI 创建 Uni-app Vue 3 项目到 `frontend/` 目录
- [ ] 安装 `@dcloudio/uni-ui` 组件库，配置按需引入（easycom 自动导入）
- [ ] 配置 `pages.json`：首页（聊天入口）、历史页、我的页（占位）三个 TabBar 页
- [ ] 实现 TabBar 布局和页面导航
- [ ] 配置 `manifest.json`：H5 运行端口、API 代理地址
- [ ] 封装 API 请求模块 `frontend/src/api/`：base URL 从环境变量读取，统一错误处理
- [ ] 封装 `frontend/src/utils/request.ts`：基于 uni.request 的 HTTP 请求封装，含超时、错误拦截
- [ ] 在 `request.ts` 中实现 `client_user_id` 自动注入：首次运行时生成 UUID 存入 localStorage，后续所有请求自动携带（无需每次手动传）
- [ ] **开工前确认**：取消注释 `docker/.env` 中的 `CORS_ALLOW_ORIGINS`，填入本地 dev server 地址（如 `["http://localhost:5173","http://localhost:8080"]`），否则浏览器会拦截跨域请求
- [ ] 验证：H5 编译成功，Nginx 代理可访问，TabBar 页面切换正常，API 模块可调通 `/health`
- **交付物**：可编译运行的 Uni-app 项目骨架 + API 模块 + TabBar 页面
- **工作量**：1 天

### Story 3.2: 实现聊天对话页：消息气泡列表 + 输入框 + 发送按钮

- [ ] 创建聊天页 `frontend/src/pages/chat/index.vue`
- [ ] 实现消息气泡列表：区分用户消息（右侧气泡）和 AI 消息（左侧气泡）
- [ ] 实现底部输入框 + 发送按钮，支持文字输入
- [ ] 实现消息发送逻辑：调用 `POST /api/v1/chat/completions`，请求体包含 `{ session_id?, message, asset_ids?, client_user_id? }`，不携带 `mode` 和 `file_ids`
- [ ] 实现 AI 回复的完整渲染（本 Story 先用纯文本渲染，3.3/3.4 再增强）
- [ ] 实现自动滚动到最新消息
- [ ] 实现 loading 状态：发送后 AI 回复到达前展示加载动画
- [ ] 实现新建会话逻辑：首次发送时创建会话，后续消息复用 `session_id`
- [ ] 验证：可在聊天页发送消息，收到后端 mock 或 live 的 AI 回复
- **交付物**：聊天页 UI + 消息发送/接收逻辑
- **工作量**：0.75 天

### Story 3.3: 实现流式输出打字机效果：对接后端 SSE 接口，逐字渲染 AI 回复

- [ ] 实现 SSE 流式读取模块 `frontend/src/utils/sse.ts`：
  - 使用 `fetch` POST 请求 + `ReadableStream` 逐块读取
  - 解析 SSE 事件格式 `data: {...}\n\n`
  - 按 `event` 类型分发：`message_start` / `delta` / `figure_result` / `message_end` / `error`
- [ ] 改造聊天页消息发送逻辑：将原来的等待完整响应改为接收 SSE 流
- [ ] 实现打字机效果：每次 `delta` 事件追加文本到当前 AI 消息，视图实时更新
- [ ] 处理 `message_start`（记录 session_id）和 `message_end`（标记消息完成，触发 figure_result 超时检查）
- [ ] 处理 `figure_result` 事件：将对应 `python:figure` 代码块替换为渲染图片（详见 Story 3.7+4.4）；`message_end` 后 5 秒内仍未收到 figure_result 的代码块标记为 `failed`
- [ ] 处理 `error` 事件：在消息气泡中展示错误提示
- [ ] 处理网络中断和超时：SSE 连接异常时展示重试按钮
- [ ] 验证：发送消息后 AI 回复逐字出现，完整回复后标记完成
- **交付物**：SSE 流式读取模块 + 聊天页打字机效果
- **工作量**：1.75 天

### Story 3.4: 集成 markdown-it + KaTeX：渲染 AI 回复中的 Markdown 格式和数学公式

- [ ] 安装 markdown-it、markdown-it-katex（或 markdown-it-texmath）和 katex 依赖
- [ ] 实现 Markdown 渲染组件 `frontend/src/components/MarkdownRenderer.vue`：
  - markdown-it 解析 Markdown 为 HTML
  - KaTeX 插件渲染数学公式：行内 `$...$` 和块级 `$$...$$`
  - 代码块使用自定义 fence renderer，标记语言类型和 `python:figure`
- [ ] 在 AI 消息气泡中使用 MarkdownRenderer 替换纯文本渲染
- [ ] 处理流式场景下的增量渲染：delta 文本累积到完整 Markdown 后重新解析
- [ ] 样式适配：消息气泡中的 Markdown 样式（标题、列表、表格、代码块、公式）与页面风格统一
- [ ] 验证：AI 回复中的标题、列表、代码块、行内公式和块级公式均正确渲染
- **交付物**：MarkdownRenderer 组件 + 聊天页公式渲染
- **工作量**：1 天

### Story 3.5: 实现拍照/选图上传：调用摄像头或相册，压缩图片后上传到后端

- [ ] 实现图片选择模块 `frontend/src/utils/image.ts`：
  - 调用 `uni.chooseImage` 支持拍照和相册选择
  - 使用 Canvas 压缩图片：最大长边 1600px，JPEG quality 85
  - 返回压缩后的临时文件路径
- [ ] 实现上传逻辑：调用 `POST /api/v1/files/upload` 上传压缩后的图片
- [ ] 在聊天页输入框区域添加图片选择按钮（相机/相册图标）
- [ ] 上传成功后获取 `asset_id`，在后续聊天请求中携带 `asset_ids`
- [ ] 处理上传失败：展示错误提示，允许重试
- [ ] 验证：选择/拍摄图片 → 压缩 → 上传成功 → 获得 `asset_id`
- **交付物**：图片选择压缩模块 + 上传逻辑 + 聊天页图片入口
- **工作量**：1 天

### Story 3.6: 图片预览：上传后在聊天框中展示图片缩略图

- [ ] 实现图片消息气泡组件：用户发送的图片在右侧展示缩略图
- [ ] 点击缩略图调用 `uni.previewImage` 全屏预览
- [ ] 上传中的图片展示上传进度/加载状态
- [ ] AI 消息中如果引用图片（沙箱生成图等）也在气泡中展示缩略图
- [ ] 图片缩略图尺寸和圆角与消息气泡风格统一
- [ ] 验证：上传图片后聊天框展示缩略图，点击可全屏预览
- **交付物**：图片消息气泡组件 + 缩略图预览
- **工作量**：0.5 天

### Story 3.7 + 4.4: 实现 AI 回复代码块识别与 python:figure 图片渲染（合并实施）

- [ ] 改造 markdown-it fence renderer：识别 `python:figure` 语言标记
- [ ] 实现普通代码块组件 `CodeBlock.vue`：语言标签 + 代码内容 + 复制按钮
- [ ] 实现 python:figure 代码块组件 `FigureBlock.vue`，包含简化状态机：
  - `waiting`：展示代码折叠区域 + "图形生成中"占位（等待 figure_result 事件）
  - `success`：展示生成的图片，点击可全屏预览
  - `failed`：展示提示信息（message_end 后未收到 figure_result，后端渲染失败）
- [ ] 在 SSE 模块中，收到 `figure_result` 事件时，将对应 `FigureBlock` 状态更新为 `success` 并渲染 `image_url`
- [ ] 在 `message_end` 后 5 秒内未收到 figure_result 的 `FigureBlock` 标记为 `failed`
- [ ] **python:figure 识别时机**：流式期间 markdown-it fence renderer 遇到 ` ```python:figure ` 就立即渲染为 `FigureBlock`（`waiting` 状态），不等 `message_end`；`message_end` 后才触发超时计时
- [ ] 不主动调用 `POST /api/v1/sandbox/python-figure`，执行由后端 Agent 完成
- [ ] 验证：AI 回复中的普通代码块展示代码卡片；python:figure 代码块在收到 figure_result 后展示生成图片
- **交付物**：CodeBlock 组件 + FigureBlock 组件 + figure_result 事件接收逻辑
- **工作量**：1.5 天

### Story 4.3: 前端实现「不甚理解」/「我会了」悬浮反馈按钮

- [ ] 实现悬浮反馈按钮组件 `FeedbackButtons.vue`：
  - AI 消息完成后在消息底部展示「不甚理解」和「我会了」两个按钮
  - 按钮仅对 AI 最后一条消息可见，用户发送新消息后隐藏
- [ ] 实现反馈发送逻辑：
  - 「不甚理解」：发送自然语言消息（如"我还是不太理解，请更细致地引导我"），Agent 规划层识别为 `step_breakdown` 策略
  - 「我会了」：发送自然语言消息（如"我理解了，请总结一下并给我一道相似题"），Agent 规划层识别为 `summarize_and_similar` 策略
- [ ] 反馈按钮发送后进入等待 AI 回复状态（复用 3.3 的 SSE 打字机效果）
- [ ] 样式设计：按钮颜色与消息气泡风格统一，点击后有视觉反馈
- [ ] 验证：点击「不甚理解」后 AI 输出分步拆解，点击「我会了」后 AI 输出总结和相似题
- **交付物**：FeedbackButtons 组件 + 反馈意图消息发送逻辑
- **工作量**：0.5 天

## 8. 依赖关系

```
Story 3.1 (项目初始化)
  ├──→ Story 3.2 (聊天页 UI)
  │      ├──→ Story 3.3 (SSE 流式 + figure_result)
  │      │      ├──→ Story 3.4 (Markdown/KaTeX)
  │      │      │      └──→ Story 3.7+4.4 (代码块/figure_result 渲染)
  │      │      └──→ Story 4.3 (反馈按钮，不再依赖 Dify 工作流)
  │      ├──→ Story 3.5 (图片上传)
  │             └──→ Story 3.6 (图片预览)
```

关键依赖说明：
1. Story 3.2 和 3.3 紧密关联，3.2 先实现完整消息收发，3.3 改造为 SSE 流式，建议连续实施
2. Story 3.7 和 4.4 合并为一个 Story 实施，因为代码块识别和 figure_result 接收是同一条实现路径
3. Story 4.3 不再依赖 Dify 工作流（4.1/4.2 已由 Agent 内置），可在 Story 3.3 完成后直接实施
4. Story 3.5/3.6 可与 3.3/3.4 部分并行，图片上传不依赖 SSE 流式

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| SSE 在 Uni-app H5 中 fetch + ReadableStream 兼容性不稳定 | 中 | 高 | 提前在 Story 3.3 验证 SSE 可行性；若 ReadableStream 不可用，回退为 XMLHttpRequest + chunked 读取；预留 `#ifdef` 条件编译接口 |
| markdown-it + KaTeX 在流式增量渲染时闪烁或性能差 | 中 | 中 | 使用 debounce 或 requestAnimationFrame 控制重渲染频率；delta 累积到合理粒度后批量解析 |
| python:figure 代码块在流式输出中逐字到达，标记不完整导致误判 | 中 | 中 | markdown-it fence renderer 遇到完整的 ` ```python:figure ` 标记时立即渲染为 `waiting` 状态的 FigureBlock；流式期间代码块尚未闭合时按普通文本渲染，闭合后替换；`message_end` 后只做 5 秒超时计时 |
| figure_result 事件未到达（后端沙箱失败）导致 FigureBlock 永久 waiting | 低 | 中 | 在 `message_end` 后设置超时（如 5s），超时后将 waiting 状态的 FigureBlock 标记为 failed |
| Agent 规划层对反馈意图分类不准确 | 低 | 高 | 反馈按钮发送的消息语义高度明确，与其他意图几乎不存在歧义；可在 LLM 规划 Prompt 中补充分类示例 |
| 图片压缩在前端 Canvas 中跨域或格式问题 | 低 | 中 | H5 环境下 Canvas 压缩通常无跨域问题；测试 png/jpeg/webp 三种格式；后端兜底压缩 |
| Nginx 代理前端静态文件缓存导致更新不生效 | 低 | 低 | 开发阶段禁用 Nginx 缓存；构建时加 hash |
| 前端项目从零搭建可能遇到 Uni-app + Vue 3 + uni-ui 配置陷阱 | 中 | 中 | Story 3.1 预留充足时间验证编译和组件引入；参考 @dcloudio/uni-ui 官方文档和示例项目 |
| KaTeX CSS 未加载导致公式渲染为原始 LaTeX 源码 | 低 | 中 | 在 App.vue 全局引入 KaTeX CSS；渲染前检查 katex 对象是否可用 |

## 10. 时间估算

| Story | 工作量 | 依赖 | 说明 |
|-------|--------|------|------|
| Story 3.1: 初始化 Uni-app 项目 | 1 天 | 无 | 项目骨架 + API 模块 + TabBar |
| Story 3.2: 聊天对话页 | 0.75 天 | 3.1 | 消息气泡 + 发送逻辑（无 mode/file_ids） |
| Story 3.3: SSE 流式打字机效果 | 1.75 天 | 3.2 | fetch + ReadableStream + 逐字渲染 + figure_result 分发 |
| Story 3.4: Markdown/KaTeX 渲染 | 1 天 | 3.3 | markdown-it + KaTeX 组件 |
| Story 3.5: 拍照/选图上传 | 1 天 | 3.1 | 图片选择 + 压缩 + 上传 |
| Story 3.6: 图片预览 | 0.5 天 | 3.5 | 缩略图气泡 + 全屏预览 |
| Story 3.7+4.4: 代码块识别与图片渲染 | 1.5 天 | 3.4 | CodeBlock + FigureBlock + figure_result 接收（无主动沙箱调用） |
| Story 4.3: 反馈按钮 | 0.5 天 | 3.3 | 前端按钮 + 意图消息发送（不依赖 Dify 工作流） |
| **合计** | **8 天** | | 较原方案节省 2.5 天 |

**可并行路径**：
- 前端路径（3.1 → 3.2 → 3.3 → 3.4 → 3.7+4.4 → 4.3）约 6.5 天
- 图片路径（3.5 → 3.6）约 1.5 天，可在 3.3/3.4 期间并行

**实际关键路径**：约 6.5 天

## 11. 预期产出

1. 可编译运行的 Uni-app (Vue 3) 前端工程，H5 端可正常访问
2. 聊天页核心交互闭环：文字/图片消息发送、SSE 流式打字机、Markdown/KaTeX 渲染
3. 图片上传预览：拍照/选图 → 压缩 → 上传 → 缩略图展示
4. python:figure 代码块渲染：代码识别 → 等待 figure_result → 图片渲染（后端主导执行）
5. 反馈按钮交互：「不甚理解」→ Agent 输出分步拆解 / 「我会了」→ Agent 输出总结+相似题

## 12. 建议执行顺序

1. **Story 3.1**（项目初始化）— 必须最先完成，后续所有前端 Story 依赖此骨架
2. **Story 3.2**（聊天页 UI）— 纯文本消息收发
3. **Story 3.3**（SSE 流式打字机）— 改造 3.2 为流式，核心技术难点，含 figure_result 事件分发
4. **Story 3.5 + 3.6**（图片上传预览）— 可与 3.4 部分并行
5. **Story 3.4**（Markdown/KaTeX 渲染）— AI 回复增强渲染
6. **Story 3.7 + 4.4**（代码块/figure_result 渲染）— 依赖 3.4 的 markdown-it 自定义 fence
7. **Story 4.3**（反馈按钮）— 依赖 3.3 的 SSE，不再依赖 Dify 工作流
8. **全链路端到端验收** — 使用几何题图跑完整闭环
