# Study Helper 技术栈选型

## 项目结构

```
studyhelper/
├── backend/                       # FastAPI 业务后端
│   ├── Dockerfile                 # 后端镜像构建
│   └── requirements.txt           # Python 依赖
├── docker/                        # Docker 部署配置
│   ├── docker-compose.yml         # 业务服务编排
│   ├── .env.example               # 环境变量模板
│   ├── sandbox/
│   │   └── Dockerfile             # 代码沙箱镜像（matplotlib + numpy）
│   └── nginx/
│       ├── nginx.conf             # Nginx 主配置
│       └── conf.d/
│           └── default.conf       # 站点配置（API代理、SSE超时）
├── docs/                          # 项目文档
│   ├── framework.md               # 技术栈选型（本文件）
│   └── prompts/                   # Prompt 模板
│       ├── node_a_question_recognition.md
│       ├── node_b_knowledge_extraction.md
│       └── node_c_socratic_tutor.md
├── scripts/                       # 运维脚本
│   └── setup.sh                   # 一键部署脚本
├── tasks/                         # 任务管理（Scrum）
│   ├── product_backlog.md         # 产品待办列表
│   ├── sprints/sprint1/           # Sprint 迭代
│   └── lessons.md                 # 经验教训
├── dify/                          # Dify 官方仓库（git clone，不入版本控制）
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
└───────┬──────────────────────────┬───────────────────┬─────────────┘
        │                          │                   │
        ▼                          ▼                   ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ PostgreSQL   │    │    Dify (AI)     │    │  代码沙箱容器     │
│ + pgvector   │    │ ┌──────────────┐ │    │  (matplotlib)    │
│              │    │ │ 节点A: 识别   │ │    │  network: none   │
│ users        │    │ │ 节点B: 提取   │ │    │  read_only       │
│ sessions     │    │ │ 节点C: 解答   │ │    │  5s timeout      │
│ messages     │    │ └──────────────┘ │    └──────────────────┘
└──────────────┘    │ + Weaviate      │              │
      ▲             │ + Dify Sandbox  │              │
      │             │ + Plugin Daemon │              ▼
┌─────┴──────┐      └──────────────────┘     ┌──────────────┐
│   Redis    │              │                 │    MinIO     │
│ 会话/限流   │       ┌──────┴──────┐          │ 图片/图形存储 │
│ SSE管理    │       │  大模型 API  │          └──────────────┘
└────────────┘       │ Qwen/GPT/   │                 ▲
                     │ DeepSeek    │                 │
                     └─────────────┘          沙箱图片回传

                    ─── studyhelper_net（共享 Docker 网络）───
```

### 双 docker-compose 架构

```
Dify 官方 docker-compose         StudyHelper docker-compose
┌──────────────────┐             ┌──────────────────────────────┐
│ api              │◄───────────►│ nginx (:8080) — 反向代理       │
│ worker           │   共享网络   │ api (:8000) — FastAPI 业务后端 │
│ web              │             │ business_db — PG + pgvector   │
│ db_postgres      │             │ redis — 会话/限流/SSE管理      │
│ redis (Dify专属)  │             │ minio — 对象存储              │
│ weaviate         │             │ code_sandbox — 绘图沙箱(按需)  │
│ sandbox(Dify内置) │             └──────────────────────────────┘
│ nginx (Dify专属)  │
│ plugin_daemon    │
└──────────────────┘
       studyhelper_net（外部共享网络）
```

## 各层技术选型

### 前端层：Uni-app (Vue 3)

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 跨端框架 | Uni-app (Vue 3) | 微信小程序支持最成熟；App 通过 DCloud 云打包一键出 Android/iOS；中文生态和插件最大；条件编译 `#ifdef` 粒度细 |
| UI 框架 | 待定（uv-ui / uView Plus） | Sprint 3 前确定 |
| Markdown 渲染 | markdown-it | 轻量、插件生态丰富 |
| 数学公式 | KaTeX | 渲染速度远快于 MathJax，适合流式输出场景 |
| 几何图形 | Python + matplotlib（FastAPI 沙箱执行） | AI 输出 Python 绘图代码，后端独立沙箱执行生成图片，前端展示 |

**公式渲染跨端策略：**

| 平台 | 方案 | 说明 |
|------|------|------|
| H5 | markdown-it + KaTeX 直接渲染 | 无障碍，主开发调试环境 |
| 微信小程序 | mini-latex 或服务端渲染为图片 | 小程序无 DOM，KaTeX 不可用 |
| App | webview 嵌套 H5 页面 | 复用 H5 渲染能力 |

### 业务后端：Python (FastAPI)

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 语言 | Python 3.11+ | AI Agent 生态最成熟；LangChain/LangGraph/Dify SDK 均首发 Python |
| Web 框架 | FastAPI | 原生 async、自动 OpenAPI 文档、流式响应支持好 |
| ORM | SQLAlchemy 2.0 | Python 生态主流，支持异步 |
| 数据库迁移 | Alembic | SQLAlchemy 官方推荐 |
| 对象存储 | MinIO（本地开发）/ OSS（生产） | 本地开发用 MinIO 兼容 S3 协议 |
| 代码沙箱 | Docker 容器隔离 | 几何绘图 Python 代码在独立容器中执行，与业务后端物理隔离 |

**代码沙箱架构：**

```
节点 C 输出 python:figure 代码
        ↓
FastAPI 接收代码 → docker run 启动临时沙箱容器
        ↓
容器内 matplotlib 生成 figure.png（写入 /tmp/sandbox/）
        ↓
FastAPI 通过 docker cp 提取 figure.png
        ↓
FastAPI 上传至 MinIO → 返回图片 URL 给前端
        ↓
docker rm 销毁容器
```

沙箱安全策略：
- 禁止网络访问（`--network=none`）
- 只读文件系统（只写 /tmp，tmpfs 256MB）
- CPU 限制（1 核）、内存限制（256MB）
- 执行超时 5 秒
- 预装 matplotlib + numpy，无其他依赖
- 非 root 用户执行代码

### 数据库：PostgreSQL + pgvector

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 关系型数据库 | PostgreSQL 15+ | pgvector 扩展支持向量检索，无需额外引入向量库 |
| 向量扩展 | pgvector | 未来 RAG 场景用于相似题检索 |
| 缓存 | Redis | 会话管理、限流 |

### AI 编排层：Dify（Docker 自部署）

| 决策项 | 选型 | 理由 |
|--------|------|------|
| 编排平台 | Dify 开源版 | 不造轮子；可视化 Prompt 调试即时生效；工作流分支拖拽编排；内置多模型切换、对话管理、token 统计；未来 RAG 开箱即用 |
| 部署方式 | Docker Compose 本地部署 | 开发阶段本地运行，生产环境可迁云 |

### 底层大模型

| 用途 | 模型 | 理由 |
|------|------|------|
| 多模态识别（OCR） | Qwen-VL-Max / GPT-4o | 视觉理解能力强，识别题目图片 |
| 核心解题 | Qwen-Max / Claude Sonnet / DeepSeek | 推理能力强，支持 CoT |
| 相似题生成 | 同核心解题模型 | 复用同一模型，按 Prompt 切换任务 |

> 模型选择不绑定，通过 Dify 可视化切换，根据效果和成本动态调整。

## 本地开发环境

| 工具 | 版本要求 | 说明 |
|------|----------|------|
| Docker | 24+ | 运行 Dify、PostgreSQL、Redis、MinIO、代码沙箱容器 |
| Node.js | 18+ | Uni-app 编译构建 |
| Python | 3.11+ | FastAPI 后端 |
| HBuilderX | 最新 | Uni-app 官方 IDE（可选，VS Code 也可） |

## 决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-05-07 | 选择 Uni-app 而非 Taro | 微信小程序支持最成熟，App 打包链路更简单，中文生态更大 |
| 2026-05-07 | 选择 Dify 而非自建编排 | 避免造轮子；AI 产品的核心迭代是 Prompt 调优，Dify 让产品侧能快速试错 |
| 2026-05-07 | 选择 Python 而非 Go/Node.js | AI Agent 生态最成熟，LangChain/Dify SDK 均首发 Python |
| 2026-05-07 | 选择 FastAPI 而非 Django/Flask | 原生 async 适合流式输出场景，自动 OpenAPI 文档 |
| 2026-05-07 | 几何图形用 Python+matplotlib 而非 SVG | 模型写 Python 逻辑更自然；matplotlib 处理坐标变换、辅助线、标注更完善 |
| 2026-05-07 | 代码沙箱用 FastAPI 独立 Docker 容器而非 Dify 内置沙箱 | 与 Dify 物理隔离，自定义安全策略，沙箱被突破不影响业务系统 |

## 关键设计点

### 1. 双 docker-compose 隔离

Dify 使用官方 docker-compose 运行，不修改其配置，方便 `git pull` 升级版本。StudyHelper 业务服务使用独立 docker-compose，两者通过 `studyhelper_net` 外部共享网络互联。

**好处**：Dify 版本升级不会影响业务服务配置；业务服务重启不影响 Dify 运行。

### 2. 业务数据库与 Dify 数据库分离

Dify 自带 PostgreSQL 实例（端口 5432），StudyHelper 使用独立的 `business_db` 实例（端口映射 5433 避免冲突）。Dify 管理对话和 AI 工作流数据，StudyHelper 管理用户、会话、知识点打标等业务数据。

**好处**：数据职责清晰；Dify 升级不会丢失业务数据；可独立备份和迁移。

### 3. 代码沙箱按需启动

`code_sandbox` 服务配置了 `profiles: [sandbox]`，不会在 `docker compose up` 时自动启动。FastAPI 通过 Docker SDK（挂载 `/var/run/docker.sock`）按需创建容器执行代码，执行完毕后销毁，避免资源常驻占用。`requirements.txt` 中包含 `docker>=7.0.0` 用于 Docker SDK 调用。

### 4. 服务分阶段启动（profiles）

backend 和 nginx 通过 Docker Compose profiles 控制启动时机，避免代码未就绪时容器无限重启：

```bash
docker compose up -d                              # 基础设施（PG、Redis、MinIO）
docker compose --profile backend up -d            # Sprint 2：后端就绪后
docker compose --profile frontend up -d           # Sprint 3：前端构建后
docker compose --profile backend --profile frontend up -d  # 全量启动
```

### 4. 两种沙箱并存

Dify 内置沙箱用于工作流中的轻量代码执行（如数据处理、JSON 转换），StudyHelper 独立沙箱用于几何图形 Python 绘图代码执行。前者在 Dify 容器内，后者完全隔离，职责不同、安全等级不同。

### 5. MinIO 统一存储

用户上传的题目图片和沙箱生成的几何图形图片统一存储在 MinIO 中。本地开发用 MinIO 兼容 S3 协议，生产环境可无缝切换到阿里云 OSS 或其他 S3 兼容存储。

### 6. Nginx 作为统一入口

前端和 API 通过 Nginx 统一入口（`:8080`），避免跨域问题。SSE 流式接口单独配置 300s 超时，防止 nginx 默认 60s 超时截断大模型响应。

### 7. Redis 独立于 Dify

Dify 有自己的 Redis 实例，StudyHelper 使用独立的 Redis。两者职责不同：Dify Redis 管理工作流和 Celery 队列，StudyHelper Redis 管理用户会话、SSE 连接和接口限流。业务端口 6380（避免与 Dify 的 6379 冲突）。
