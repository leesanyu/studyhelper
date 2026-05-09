# Sprint 2: 业务后端与数据库搭建

## 目标

搭建 StudyHelper 业务后端，完成 FastAPI 工程、数据库、Dify API 中转、图片上传代理、会话管理和 Python 绘图沙箱，为 Sprint 3 前端聊天页联调提供稳定接口。

## 范围

对应产品待办 **Epic 2** 的全部 Story（2.1 - 2.6），并纳入 **Story 4.5** 的最小回归集建设作为 Sprint 验收支撑。

## 不在本 Sprint 范围

1. 不实现 Uni-app 前端页面和聊天 UI。
2. 不实现完整注册/登录，只支持匿名用户或本地用户标识。
3. 不实现错题本、薄弱点雷达图和练习模块。
4. 不把 Python 绘图执行放回 Dify；Dify 仍只负责生成 `python:figure` 代码。
5. 不让前端直接调用 Dify，所有 Dify 访问都通过 FastAPI 代理。

## 验收标准

1. FastAPI 后端可本地启动，`/health` 返回服务、数据库、Redis、MinIO 基本状态。
2. PostgreSQL migration 可创建 `users`、`chat_sessions`、`chat_messages`、`user_tags_history`、`assets` 等业务表。
3. `POST /api/v1/chat/completions` 可代理 Dify 流式聊天，返回 SSE，并持久化用户消息、AI 消息、Dify `conversation_id/message_id`。
4. `POST /api/v1/files/upload` 可接收题目图片，完成类型/大小校验，调用 Dify `/v1/files/upload` 获取 `file_id`，并保存本地或 MinIO 预览资产。
5. 会话接口可创建/续接会话、获取消息历史、列出会话，并保留新题目/继续追问/直接解答等状态。
6. 沙箱接口可隔离执行安全的 `python:figure` matplotlib 绘图代码，生成图片并返回 `asset_id` 或 URL；危险代码、超时、联网访问应被拒绝或中止。
7. 最小回归集覆盖：健康检查、Dify 代理 mock 流、图片上传 mock、会话持久化、沙箱成功和沙箱拒绝危险代码。

## 开工前置条件

1. `docker/.env` 中 `DIFY_API_KEY` 必须替换为 Sprint 1 最终 Dify App 的 Service API Key；本地默认值 `your-dify-app-api-key` 只能用于 mock 测试。
2. 创建共享 Docker 网络 `studyhelper_net`，并确认 Dify API 容器和 StudyHelper 后端可以互相访问；live 测试需要能访问 `http://api:5001` 或本地 `DIFY_API_URL`。
3. 先启动 PostgreSQL、Redis、MinIO：`docker compose --profile backend up -d business_db redis minio`，再启动后端服务。
4. 构建沙箱镜像并固定镜像名，例如 `studyhelper-code-sandbox:latest`；后端 Docker SDK 按镜像名启动一次性容器，不依赖 compose 长驻 `code_sandbox` 服务。
5. `backend/requirements.txt` 需补齐 Sprint 2 依赖：测试、multipart 上传、图片处理和 SSE 所需依赖（如 `pytest`、`pytest-asyncio`、`python-multipart`、`Pillow`；若不用 FastAPI `StreamingResponse`，再引入 `sse-starlette`）。

## 关键设计决策

1. **后端是唯一集成边界**：前端只调用 StudyHelper FastAPI；Dify `file_id`、`conversation_id`、`message_id` 都由后端映射和持久化。
2. **匿名用户先行**：MVP 阶段使用匿名用户或本地用户标识，数据库结构为后续登录留出 `users` 表，但不阻塞 Sprint 2。
3. **Dify 流式响应透传但归一化事件**：后端保留 SSE 流式体验，同时将 Dify 原始事件转换为前端稳定事件类型。
4. **图片双轨存储**：Dify `file_id` 用于工作流识别；MinIO 或本地对象用于预览、历史追溯和审计。
5. **沙箱默认拒绝高风险能力**：无网络、只读文件系统、资源限制、执行超时，输出文件只允许写入受控临时目录。

## 后端接口契约

| 接口 | 方法 | 用途 | Sprint 2 最小响应 |
|------|------|------|-------------------|
| `/health` | GET | 服务健康检查 | `status`、数据库、Redis、MinIO 状态 |
| `/api/v1/files/upload` | POST | 上传题目图片并代理 Dify 文件上传 | `asset_id`、`preview_url`、`dify_file_id`、`mime_type`、`size` |
| `/api/v1/chat/completions` | POST | 发送消息并流式代理 Dify Chatflow | SSE：`message_start`、`delta`、`message_end`、`error` |
| `/api/v1/sessions` | POST/GET | 创建会话、查询会话列表 | `session_id`、标题、状态、最近消息摘要 |
| `/api/v1/sessions/{session_id}` | GET | 查询会话详情 | 会话元数据、消息列表、附件和知识点摘要 |
| `/api/v1/sandbox/python-figure` | POST | 执行 `python:figure` 绘图代码 | `asset_id`、`image_url`、尺寸、耗时、stderr 摘要 |

## Story 分解与实施任务

### Story 2.1: 初始化 FastAPI 工程：项目结构、路由、配置管理、日志、异常处理

- [x] 建立后端包结构：`backend/app/main.py`、`backend/app/api/`、`backend/app/core/`、`backend/app/models/`、`backend/app/schemas/`、`backend/app/services/`。
- [x] 实现配置加载：从环境变量读取数据库、Redis、MinIO、Dify、沙箱配置。
- [x] 补齐 `backend/requirements.txt`：测试、multipart 上传、图片处理、Dify HTTP 客户端和 SSE 所需依赖。
- [x] 补充本地启动说明：如何创建 `studyhelper_net`、如何启动业务依赖、如何运行后端和测试。
- [x] 实现统一日志和请求 ID，保证 SSE、上传、沙箱执行日志可追踪。
- [x] 实现统一异常响应结构，区分参数错误、上游 Dify 错误、沙箱错误和内部错误。
- [x] 提供 `/health` 和 `/api/v1/health`。
- [x] 添加基础测试框架和健康检查测试。
- **交付物**：可启动的 FastAPI 后端基础工程。
- **工作量**：1 天

### Story 2.2: 设计并创建 PostgreSQL 数据库表：users（可匿名占位）、chat_sessions、chat_messages、user_tags_history

- [x] 接入 SQLAlchemy async engine 和 Alembic migration。
- [x] 设计 `users` 表：支持匿名用户、本地用户标识和后续登录扩展。
- [x] 设计 `chat_sessions` 表：保存会话标题、当前状态、Dify `conversation_id`、当前题目摘要、创建/更新时间。
- [x] 设计 `chat_messages` 表：保存用户消息、AI 消息、Dify `message_id`、消息类型、附件、知识点标签和原始元数据。
- [x] 设计 `user_tags_history` 表：记录对话产生的知识点标签，为 Epic 5 聚合分析提供数据源。
- [x] 设计 `assets` 表：记录用户上传图片、Dify `file_id`、沙箱生成图片、对象存储 key、URL、MIME、大小、宽高和归属会话/消息。
- [x] 编写 migration 和模型测试，验证建表、基础插入和外键关系。
- **交付物**：可迁移、可回滚、可被服务层使用的数据模型。
- **工作量**：1 天

### Story 2.3: 对接 Dify API，封装流式聊天接口 `POST /api/v1/chat/completions`（SSE 返回），映射 Dify `conversation_id/message_id`

- [x] 实现 Dify client：封装 `/v1/chat-messages` 流式调用、错误处理、超时和认证。
- [x] 定义前端请求结构：`session_id`、`message`、`mode`、`file_ids`、`asset_ids`、`client_user_id`。
- [x] 定义 SSE 事件结构：`message_start`、`delta`、`message_end`、`error`，屏蔽 Dify 原始事件差异。
- [x] 首轮新题、继续追问、直接解答统一走后端会话状态，由后端决定传给 Dify 的 `conversation_id`，并把后端 `asset_id` 转换为 Dify `files` 所需的 `upload_file_id` 引用。（当前完成已有会话续接、Dify `conversation_id` 回写和 `asset_id` 映射）
- [x] 持久化用户消息、AI 消息、Dify `conversation_id/message_id`、知识点标签和题目上下文摘要。
- [x] 编写 Dify mock 流测试，验证 SSE 不缓冲、事件顺序稳定、异常能被转成 `error` 事件。
- **交付物**：前端可直接使用的流式聊天后端入口。
- **工作量**：1.5 天

### Story 2.4: 实现图片上传代理：接收图片 → 校验/压缩 → 调用 Dify `/v1/files/upload` 获取 `file_id`，本地或 MinIO 存储仅用于预览、审计和历史追溯

- [x] 实现 `POST /api/v1/files/upload`，支持 multipart 图片上传。
- [x] 校验文件类型、大小、扩展名和图片头，拒绝非图片或超限文件。
- [x] 视图片大小实现服务端压缩；如引入 Pillow，需补充依赖和压缩测试。
- [x] 调用 Dify `/v1/files/upload`，传入后端匿名用户标识，保存返回的 `file_id`、文件名、MIME、大小和用途。
- [x] 将原图或压缩后图片存入 MinIO 或本地对象目录，写入 `assets` 表，返回前端可预览的 `asset_id` 和 URL。（当前实现本地对象目录；MinIO 适配待后续切换）
- [x] 编写上传测试：合法图片、非法 MIME、超限文件、Dify 上传失败、MinIO 写入失败。（当前以本地对象存储失败覆盖对象存储失败分支）
- **交付物**：图片上传代理接口和可追溯资产记录。
- **工作量**：1 天

### Story 2.5: 对话管理：创建/续接会话、获取历史消息、会话列表、同步新题目/继续追问/直接解答状态

- [x] 实现创建会话接口，支持匿名用户和初始题目附件。
- [x] 实现会话列表接口，按更新时间倒序返回标题、最后消息、学科和知识点摘要。
- [x] 实现会话详情与消息历史接口，返回消息、附件、知识点、Dify 映射信息和沙箱图片引用。
- [x] 实现会话状态更新：新题目覆盖上下文，继续追问复用上下文，直接解答后保留上下文。
- [x] 明确删除策略：Sprint 2 只做软删除或不做删除，避免误删调试数据。（当前不提供删除接口；模型保留 `deleted_at`）
- [x] 编写服务层测试，验证消息顺序、会话状态和匿名用户隔离。
- **交付物**：前端历史页和聊天页可复用的会话 API。
- **工作量**：1 天

### Story 2.6: 代码沙箱服务：Docker 容器隔离执行 `python:figure` 绘图代码，生成图片并返回 `asset_id` 或 URL（安全策略：禁止网络、只读文件系统、5 秒超时、资源限制）

- [x] 固化沙箱镜像构建：基于 `docker/sandbox/Dockerfile`，包含 matplotlib、numpy 和非 root 用户，并命名为 `studyhelper-code-sandbox:latest`。
- [x] 实现 `POST /api/v1/sandbox/python-figure`，请求体包含代码、会话 ID、消息 ID 和可选图像规格。
- [x] 在执行前做静态校验：限制代码长度，拒绝 `import os`、`subprocess`、`socket`、文件系统遍历等高风险能力。
- [ ] 通过 Docker SDK 按需启动一次性沙箱容器，设置无网络、只读根文件系统、CPU/内存限制和 5 秒超时；资源限制以 Docker SDK 参数为准，不依赖 compose `deploy` 字段。（执行器代码已落地，真实 Docker live 验证待补）
- [ ] 约定输出文件路径，只允许生成 PNG；执行完成后提取图片并写入 MinIO 或本地对象目录。
- [x] 返回 `asset_id`、URL、图片尺寸、执行耗时和 stderr 摘要。
- [ ] 编写沙箱测试：安全绘图成功、语法错误、超时、危险 import、无输出文件、生成非 PNG。（当前覆盖安全绘图和危险 import）
- **交付物**：可被前端 Story 4.4 调用的绘图沙箱后端能力。
- **工作量**：2 天

### Story 4.5: 建立核心答疑回归集：覆盖真实题图、直接解答、引导式解答、反馈分支和跨学科样例，作为 Sprint 验收固定检查

- [x] 建立 `tests/questions/` 样例索引，至少纳入当前两张几何题图。
- [ ] 增加后端回归测试入口，支持 mock Dify 和 live Dify 两种模式。（当前先落地 mock 回归入口，live Dify 待补）
- [x] 固化 Sprint 1 几何题关键断言：图片只进入「题目识别」，下游解题节点使用文本上下文；后端至少保存 `current_question/current_diagram/current_knowledge` 相关元数据。
- [x] 为后续跨学科题图预留用例分类：数学、物理/化学、英语。
- [ ] 将回归命令写入 Sprint 2 验收记录。（已写入后端启动说明，Sprint 2 review 待补）
- **交付物**：后续 Sprint 可复用的最小回归测试入口。
- **工作量**：0.5 天

## 依赖关系

1. Story 2.3 依赖 Story 2.1 的工程结构和 Story 2.2 的会话/消息表。
2. Story 2.4 依赖 Story 2.1 的配置管理和对象存储配置。
3. Story 2.5 依赖 Story 2.2 和 Story 2.3 的会话映射。
4. Story 2.6 可与 2.3/2.4 部分并行，但最终资产返回格式应与 2.4 的资产记录保持一致。
5. Story 4.5 贯穿 Sprint 2，随着每个接口完成逐步补用例。

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Dify Service API 的文件上传和流式事件字段与预期不一致 | 中 | 高 | 先用 mock 测试稳定后端契约，再用 live Dify 做一条端到端烟测 |
| SSE 被代理或测试客户端缓冲 | 中 | 中 | 后端直接返回 `text/event-stream`，测试逐事件读取；Nginx 配置留到 Sprint 3 联调 |
| Docker socket 暴露带来宿主机风险 | 中 | 高 | Sprint 2 仅本地开发使用；沙箱执行严格限制镜像、网络、资源和输出路径 |
| 沙箱安全策略不足 | 中 | 高 | 静态拒绝高风险代码 + Docker 无网络/只读/超时/资源限制，危险用例必须进入测试 |
| 数据库设计过早绑定完整账号体系 | 中 | 中 | 只做匿名用户兼容字段，完整登录留到 Epic 5 |
| Live Dify 测试依赖 API key 和容器网络 | 中 | 中 | CI/本地默认跑 mock；live 测试通过环境变量显式开启 |
| `assets` 表缺失导致上传和沙箱无法统一返回 `asset_id` | 中 | 高 | Story 2.2 将 `assets` 表列为必选表，2.4 和 2.6 统一写入 |

## 时间估算

| Story | 工作量 | 状态 |
|-------|--------|------|
| Story 2.1: 初始化 FastAPI 工程 | 1 天 | ✅ 已完成 |
| Story 2.2: 设计并创建 PostgreSQL 数据库表 | 1 天 | ✅ 已完成 |
| Story 2.3: 对接 Dify API，封装流式聊天接口 | 1.5 天 | ✅ 已完成 |
| Story 2.4: 实现图片上传代理 | 1 天 | ✅ 已完成 |
| Story 2.5: 对话管理 | 1 天 | ✅ 已完成 |
| Story 2.6: 代码沙箱服务 | 2 天 | 🚧 部分完成 |
| Story 4.5: 建立核心答疑回归集 | 0.5 天 | 🚧 部分完成 |
| **合计** | **8 天** | |

## 预期产出

- 可启动、可测试的 FastAPI 后端工程。
- Alembic 数据库迁移和核心业务表。
- 面向前端的聊天 SSE、图片上传、会话管理、沙箱绘图接口。
- Dify API 中转层和稳定的 Dify ID 映射。
- 最小后端回归测试集，为 Sprint 3 前端联调提供安全网。

## 建议执行顺序

1. Story 2.1：先搭工程骨架、配置、健康检查和测试框架。
2. Story 2.2：补数据库模型和 migration。
3. Story 2.3：实现 Dify 流式聊天代理和消息持久化。
4. Story 2.4：实现图片上传代理和资产记录。
5. Story 2.5：补会话管理接口。
6. Story 2.6：实现沙箱执行和图片产物返回。
7. Story 4.5：贯穿执行，最后补齐回归命令和验收记录。
