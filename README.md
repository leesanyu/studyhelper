# StudyHelper

AI 辅助答疑应用 —— 拍照 → AI 识别题目 → 苏格拉底式引导 / 直接解答 → 反馈互动

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Uni-app (Vue 3) + markdown-it + KaTeX |
| 后端 | FastAPI + SQLAlchemy (async) + OpenAI SDK |
| AI 编排 | Plan-and-Solve + Reflexion 四层 Agent |
| 数据库 | PostgreSQL + pgvector |
| 缓存 | Redis |
| 对象存储 | MinIO (S3 兼容) |
| 代码沙箱 | Docker 容器隔离执行 matplotlib 绘图 |
| 反向代理 | Nginx |

## 目录结构

```
studyhelper/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── agent/           # Agent 四层架构（Plan/Tool/Solve/Reflexion）
│   │   ├── api/             # 路由和依赖注入
│   │   ├── core/            # 配置、异常处理
│   │   ├── db/              # 数据库会话管理
│   │   ├── models/          # SQLAlchemy 模型
│   │   ├── schemas/         # Pydantic 请求/响应模型
│   │   └── services/        # 业务服务层
│   ├── alembic/             # 数据库迁移
│   ├── tests/               # 测试
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                # Uni-app 前端
│   ├── src/
│   │   ├── api/             # API 接口封装
│   │   ├── components/      # Vue 组件
│   │   ├── pages/           # 页面
│   │   └── utils/           # 工具模块（SSE、请求、图片压缩）
│   ├── vite.config.ts       # Vite 配置（含开发代理）
│   └── manifest.json        # Uni-app 配置
├── docker/
│   ├── docker-compose.yml   # 业务服务编排
│   ├── .env                 # 环境变量
│   ├── .env.example         # 环境变量模板
│   ├── nginx/               # Nginx 配置
│   └── sandbox/             # 代码沙箱镜像
├── docs/                    # 设计文档和 Prompt
└── tasks/                   # Scrum 任务管理
```

## 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- WSL2 (Windows) 或 Linux

## 快速开始

### 1. 配置环境变量

```bash
cp docker/.env.example docker/.env
```

编辑 `docker/.env`，填入实际配置：

| 必填项 | 说明 |
|--------|------|
| `LLM_API_KEY` | 大模型 API Key（阿里云百炼 DashScope） |
| `LLM_API_URL` | API 端点（默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`） |
| `CORS_ALLOW_ORIGINS` | 开发环境跨域白名单（如 `["http://localhost:5173"]`） |

同时在 `backend/` 目录下也创建 `.env`（内容与 `docker/.env` 一致）：

```bash
cp docker/.env backend/.env
```

### 2. 启动基础设施

```bash
cd docker
docker compose up -d business_db redis minio
```

等待健康检查通过（约 30 秒）：

```bash
docker compose ps   # 确认 3 个服务状态为 healthy
```

### 3. 数据库迁移

```bash
cd backend
PYTHONPATH=. python3 -m alembic upgrade head
```

### 4. 构建沙箱镜像（首次）

```bash
cd docker
docker compose build code_sandbox
```

### 5. 启动后端（开发模式）

```bash
cd backend
PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

验证：

```bash
curl http://localhost:8000/health
```

### 6. 启动前端（开发模式）

```bash
cd frontend
npm install    # 首次安装依赖
npm run dev:h5
```

浏览器访问 `http://localhost:5173`。

> **注意**：SSE 流式接口的代理配置在 `vite.config.ts` 中，`/api/v1/chat` 路径有专用 SSE 配置（禁用压缩和缓冲）。修改代理配置后需重启前端 dev server。

## 生产部署

```bash
cd docker

# 构建前端
cd ../frontend && npm run build:h5

# 构建沙箱镜像
cd ../docker && docker compose build code_sandbox

# 启动全部服务
docker compose --profile backend --profile frontend up -d

# 查看状态
docker compose ps
```

访问 `http://localhost:8080`（由 Nginx 统一入口）。

### 生产部署 Profiles

| Profile | 服务 | 说明 |
|---------|------|------|
| （默认） | business_db, redis, minio | 基础设施，始终启动 |
| `backend` | backend | 后端 API 服务 |
| `frontend` | nginx | 前端静态文件 + 反向代理 |
| `sandbox` | code_sandbox | 代码沙箱（仅构建镜像，不自动运行） |

## 开发说明

### 后端开发

```bash
cd backend
PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

运行测试：

```bash
cd backend
PYTHONPATH=. python3 -m pytest tests/ -v
```

### 前端开发

```bash
cd frontend
npm run dev:h5     # H5 开发模式
npm run build:h5   # H5 生产构建
```

### 模型配置

6 个场景各自配模型名，url/key 可选覆盖（未配置则用默认 `LLM_API_URL` / `LLM_API_KEY`）：

| 环境变量 | 场景 |
|----------|------|
| `LLM_MODEL_PLANNING` | 规划层：题目分类+策略选择 |
| `LLM_MODEL_QUESTION_PARSE` | 题目标准化：文字→结构化题干 |
| `LLM_MODEL_VISION` | 题目识别：图片→结构化题干 |
| `LLM_MODEL_KNOWLEDGE` | 知识点提取：题干→标签+难度 |
| `LLM_MODEL_SOLVING` | 执行层：教学回复生成 |
| `LLM_MODEL_REFLEXION` | 反思层：计算逻辑自检（仅难题触发） |

最小配置只需 `LLM_API_URL` + `LLM_API_KEY` + 6 个模型名。

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/completions` | SSE 流式聊天 |
| POST | `/api/v1/files/upload` | 图片上传 |
| POST | `/api/v1/sessions` | 创建会话 |
| GET | `/api/v1/sessions` | 会话列表 |
| GET | `/api/v1/sessions/{id}` | 会话详情 |
| POST | `/api/v1/sandbox/python-figure` | 沙箱执行 Python 绘图 |
| GET | `/health` | 健康检查 |

## 常见问题

**Q: 前端发消息后无数据返回？**

检查以下几点：
1. 后端是否正常运行（`curl http://localhost:8000/health`）
2. 前端 dev server 是否重启过（代理配置变更后需重启）
3. `LLM_API_KEY` 是否配置正确
4. 浏览器 F12 Network 中请求状态是否为 pending（说明代理缓冲了 SSE）

**Q: 数据库连接失败？**

确认 `docker/.env` 和 `backend/.env` 中 `DB_PORT=5433`（宿主机映射端口，不是容器内 5432）。

**Q: 沙箱执行失败？**

确认沙箱镜像已构建：`docker images | grep studyhelper-code-sandbox`。
