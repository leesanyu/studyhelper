# Study Helper 技术栈选型

## 项目结构

```
studyhelper/
├── backend/                       # FastAPI 业务后端
│   ├── app/
│   │   ├── agent/                 # Agent 编排层（Plan-and-Solve + Reflexion）
│   │   │   ├── llm_client.py      # LLM 客户端（openai SDK 封装）
│   │   │   ├── prompts.py         # Prompt 模板
│   │   │   ├── tools.py           # Agent 工具（process_question, extract_knowledge）
│   │   │   ├── layers.py          # 规划层 + 执行层
│   │   │   ├── reflexion.py       # 反思层（正则 + LLM 两级检查）
│   │   │   └── service.py         # AgentService 编排入口
│   │   ├── api/                   # FastAPI 路由
│   │   ├── models/                # SQLAlchemy ORM 模型
│   │   ├── services/              # 业务服务层
│   │   └── core/                  # 配置、异常
│   ├── Dockerfile
│   └── requirements.txt
├── docker/                        # Docker 部署配置
│   ├── docker-compose.yml         # 业务服务编排
│   ├── .env                       # 环境变量（含 LLM API 配置）
│   ├── sandbox/
│   │   └── Dockerfile             # 代码沙箱镜像（matplotlib + numpy）
│   └── nginx/
│       ├── nginx.conf             # Nginx 主配置
│       └── conf.d/
│           └── default.conf       # 站点配置（API代理、SSE超时）
├── docs/                          # 项目文档
│   ├── framework.md               # 技术栈选型（本文件）
│   └── prompts/                   # Prompt 模板
├── tasks/                         # 任务管理（Scrum）
│   ├── product_backlog.md         # 产品待办列表
│   ├── sprints/                   # Sprint 迭代
│   └── lessons.md                 # 经验教训
├── CLAUDE.md                      # Claude Code 工作指南
└── .gitignore
```

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户端                                     │
│              Uni-app (Vue 3) — H5 / 小程序 / App                     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP / SSE
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Nginx 反向代理 (:8080)                            │
│  /          → 前端静态文件                                            │
│  /api/      → FastAPI (SSE 超时 300s)                                │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       业务后端 (FastAPI :8000)                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐     │
│  │ 鉴权中间件 │ │ 聊天接口  │ │ 图片上传  │ │ 代码沙箱执行接口    │     │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────────┘     │
│                    │                                                 │
│  ┌─────────────────▼──────────────────────────────────────────┐     │
│  │              Agent 编排层（Plan-and-Solve + Reflexion）       │     │
│  │  规划层(Plan) → 工具执行(Tool) → 执行层(Solve) → 反思层(Ref) │     │
│  └─────────────────────────────────────────────────────────────┘     │
└───────┬──────────────────────────┬───────────────────┬─────────────┘
        │                          │                   │
        ▼                          ▼                   ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ PostgreSQL   │    │   大模型 API      │    │  代码沙箱容器     │
│ + pgvector   │    │ (OpenAI 兼容协议) │    │  (matplotlib)    │
│              │    │                  │    │  network: none   │
│ users        │    │ Qwen / DeepSeek  │    │  read_only       │
│ sessions     │    │ GPT / Claude     │    │  5s timeout      │
│ messages     │    │ 等任意供应商      │    └──────────────────┘
└──────────────┘    └──────────────────┘              │
      ▲                                               ▼
┌─────┴──────┐                                ┌──────────────┐
│   Redis    │                                │    MinIO     │
│ 会话/限流   │                                │ 图片/图形存储 │
│ SSE管理    │                                └──────────────┘
└────────────┘
```

## Agent 架构：Plan-and-Solve + Reflexion

```
用户输入（文字/图片）
        ↓
  [工具层] process_question
  - 图片输入：vision 模型 OCR → 结构化题干
  - 文字输入：question_parse 模型 → 结构化题干
        ↓
  [工具层] extract_knowledge
  - knowledge 模型 → 知识点 + 难度 + 学科
        ↓
  [规划层] plan()
  - planning 模型（JSON Mode）
  - 输出：strategy + tool_calls 列表（一次性，非循环）
        ↓
  [执行层] solve()
  - solving 模型（流式）
  - 解析 python:figure 代码块，触发沙箱执行
        ↓
  [反思层] reflexion_check()
  - Level 1：正则检查（零 LLM 开销，每轮必过）
  - Level 2：LLM 深度反思（仅难题或用户不满时触发）
        ↓
  SSE 流式输出给前端
```

**核心约束：**
- 不是 ReAct：规划层一次性输出 `tool_calls`，编排层按序执行，不做 LLM 循环决策
- 先缓冲再流式：执行层完整输出 → 反思层检查 → 再流式发送
- 图片走摘要：图片以摘要文本传入规划层，base64 只在工具执行时使用
- 学生优先：学生要求直接答案时，strategy 切为 `direct_answer`

## 各层技术选型

### 前端层：Uni-app (Vue 3)

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 跨端框架 | Uni-app (Vue 3) | 微信小程序支持最成熟；App 通过 DCloud 云打包一键出 Android/iOS |
| UI 框架 | uv-ui | 组件丰富，与 Uni-app 深度集成 |
| Markdown 渲染 | markdown-it | 轻量、插件生态丰富 |
| 数学公式 | KaTeX | 渲染速度远快于 MathJax，适合流式输出场景 |
| 几何图形 | Python + matplotlib（FastAPI 沙箱执行） | AI 输出 Python 绘图代码，后端独立沙箱执行生成图片，前端展示 |
| SSE 接收 | fetch + ReadableStream | 需要 POST body，EventSource 不支持 POST |

### 业务后端：Python (FastAPI)

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 语言 | Python 3.11+ | AI Agent 生态最成熟 |
| Web 框架 | FastAPI | 原生 async、自动 OpenAPI 文档、流式响应支持好 |
| LLM 客户端 | openai SDK（AsyncOpenAI） | 兼容 OpenAI 协议的供应商均可用，无需多套 SDK |
| ORM | SQLAlchemy 2.0 | Python 生态主流，支持异步 |
| 数据库迁移 | Alembic | SQLAlchemy 官方推荐 |
| 对象存储 | MinIO（本地开发）/ OSS（生产） | 本地开发用 MinIO 兼容 S3 协议 |
| 代码沙箱 | Docker 容器隔离 | 几何绘图 Python 代码在独立容器中执行，与业务后端物理隔离 |

### 大模型配置

6 个场景各自配置模型名，支持按场景覆盖 URL/Key（多供应商）：

| 场景 | 配置项 | 默认模型 |
|------|--------|---------|
| 规划层 | `LLM_MODEL_PLANNING` | qwen3.6-plus |
| 题目解析（文字） | `LLM_MODEL_QUESTION_PARSE` | qwen3.6-plus |
| 执行层 | `LLM_MODEL_SOLVING` | qwen3.6-plus |
| 反思层 | `LLM_MODEL_REFLEXION` | qwen3.6-plus |
| 视觉识别（图片） | `LLM_MODEL_VISION` | qwen-vl-max |
| 知识点提取 | `LLM_MODEL_KNOWLEDGE` | qwen3.6-plus |

默认供应商通过 `LLM_API_URL` + `LLM_API_KEY` 配置，各场景可通过 `LLM_MODEL_<SCENE>_URL` / `_KEY` 单独覆盖。

### 数据库：PostgreSQL + pgvector

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 关系型数据库 | PostgreSQL 15+ | pgvector 扩展支持向量检索，无需额外引入向量库 |
| 向量扩展 | pgvector | 未来 RAG 场景用于相似题检索 |
| 缓存 | Redis | 会话管理、限流 |

## 本地开发环境

| 工具 | 版本要求 | 说明 |
|------|----------|------|
| Docker | 24+ | 运行 PostgreSQL、Redis、MinIO、代码沙箱容器 |
| Node.js | 18+ | Uni-app 编译构建 |
| Python | 3.11+ | FastAPI 后端 |

## 决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-05-07 | 选择 Uni-app 而非 Taro | 微信小程序支持最成熟，App 打包链路更简单，中文生态更大 |
| 2026-05-07 | 选择 Python 而非 Go/Node.js | AI Agent 生态最成熟 |
| 2026-05-07 | 选择 FastAPI 而非 Django/Flask | 原生 async 适合流式输出场景，自动 OpenAPI 文档 |
| 2026-05-07 | 几何图形用 Python+matplotlib 而非 SVG | 模型写 Python 逻辑更自然；matplotlib 处理坐标变换、辅助线、标注更完善 |
| 2026-05-07 | 代码沙箱用 FastAPI 独立 Docker 容器 | 完全隔离，自定义安全策略，沙箱被突破不影响业务系统 |
| 2026-05-20 | 用自建 Agent 替换 Dify | 避免 Dify 版本升级风险；Prompt 调优直接在代码中迭代；减少外部依赖；支持多供应商灵活切换 |
| 2026-05-20 | 选择 openai SDK 而非 httpx 直调 | 兼容所有 OpenAI 协议供应商；流式/非流式统一接口；JSON Mode 内置支持 |
| 2026-05-20 | 反思层默认正则、按需 LLM | 每轮 LLM 反思成本高延迟大；正则检查零开销；仅难题或用户不满时触发 LLM 深度反思 |

## 关键设计点

### 1. Agent 编排：Plan-and-Solve（非 ReAct）

规划层一次性输出完整的 `tool_calls` 列表，编排层按序执行，不做 LLM 循环决策。这避免了 ReAct 的多轮 LLM 调用开销，同时保持了工具调用的灵活性。

### 2. 先缓冲再流式

执行层完整生成回答 → 反思层检查质量 → 通过后再流式发送给前端。这确保了用户看到的内容已经过质量检验，避免发出错误内容后再撤回。

### 3. 代码沙箱按需启动

FastAPI 通过 Docker SDK（挂载 `/var/run/docker.sock`）按需创建容器执行 Python 绘图代码，执行完毕后销毁，避免资源常驻占用。

### 4. 服务分阶段启动（profiles）

```bash
docker compose up -d                              # 基础设施（PG、Redis、MinIO）
docker compose --profile backend up -d            # 后端就绪后
docker compose --profile frontend up -d           # 前端构建后
```

### 5. MinIO 统一存储

用户上传的题目图片和沙箱生成的几何图形图片统一存储在 MinIO 中。本地开发用 MinIO 兼容 S3 协议，生产环境可无缝切换到阿里云 OSS 或其他 S3 兼容存储。

### 6. Nginx 作为统一入口

前端和 API 通过 Nginx 统一入口（`:8080`），避免跨域问题。SSE 流式接口单独配置 300s 超时，防止 nginx 默认 60s 超时截断大模型响应。
